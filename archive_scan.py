import argparse
import numpy as np
from obspy import read
import sys

# Silence tensorflow warnings
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'


if __name__ == '__main__':

    # Command line arguments parsing
    parser = argparse.ArgumentParser()
    parser.add_argument('input', help = 'Path to .csv file with archive names')
    parser.add_argument('--weights', '-w', help = 'Path to model weights', default = None)
    parser.add_argument('--favor', help = 'Use Fast-Attention Seismo-Transformer variant', action = 'store_true')
    parser.add_argument('--cnn', help = 'Use simple CNN model on top of spectrogram', action = 'store_true')
    parser.add_argument('--model', help = 'Custom model loader import, default: None', default = None)
    parser.add_argument('--loader_argv', help = 'Custom model loader arguments, default: None', default = None)
    parser.add_argument('--out', '-o', help = 'Path to output file with predictions', default = 'predictions.txt')
    parser.add_argument('--threshold', help = 'Positive prediction threshold, default: 0.95', default = 0.95)
    parser.add_argument('--threshold-p', help = 'Positive prediction threshold'
                                                ' for P-wave, default: None', default = None)
    parser.add_argument('--threshold-s', help = 'Positive prediction threshold'
                                                ' for S-wave, default: None', default = None)
    parser.add_argument('--verbose', '-v', help = 'Provide this flag for verbosity', action = 'store_true')
    parser.add_argument('--batch_size', '-b', help = 'Batch size, default: 500000 samples', default = 500000)
    parser.add_argument('--no-filter', help = 'Do not filter input waveforms', action = 'store_true')
    parser.add_argument('--no-detrend', help = 'Do not detrend input waveforms', action = 'store_true')
    parser.add_argument('--plot-positives', help = 'Plot positives waveforms', action = 'store_true')
    parser.add_argument('--plot-positives-original', help = 'Plot positives original waveforms, before '
                                                            'pre-processing',
                        action = 'store_true')
    parser.add_argument('--print-precision', help = 'Floating point precision for results pseudo-probability output',
                        default = 4)

    args = parser.parse_args()  # parse arguments

    # Validate arguments
    if not args.model and not args.weights:

        parser.print_help()
        sys.stderr.write('ERROR: No --weights specified, either specify --weights argument or use'
                         ' custom model loader with --model flag!')
        sys.exit(2)

    if args.threshold_p:
        args.threshold_p = float(args.threshold_p)
    if args.threshold_s:
        args.threshold_s = float(args.threshold_s)

    if not all([args.threshold_p, args.threshold_s]) and any([args.threshold_p, args.threshold_s]):

        if not args.threshold_p:
            sys.stderr.write('ERROR: No --threshold_p specified!')
        else:
            sys.stderr.write('ERROR: No --threshold_s specified!')

        sys.exit(2)

    args.threshold = float(args.threshold)
    if not any([args.threshold_p, args.threshold_s]):
        args.threshold_p = args.threshold
        args.threshold_s = args.threshold

    # Set default variables
    # TODO: make them customisable through command line arguments
    model_labels = {'P': 0, 'S': 1, 'N': 2}
    positive_labels = {'P': 0, 'S': 1}
    # TODO: Change threshold_s and threshold_s so they would be dynamic parameter --threshold
    #   e.g. '--threshold "p 0.92, s 0.98"'
    threshold_labels = {'P': args.threshold_p, 'S': args.threshold_s}

    frequency = 100.
    n_features = 400
    half_duration = (n_features * 0.5) / frequency

    args.batch_size = int(args.batch_size)
    args.print_precision = int(args.print_precision)

    import utils.scan_tools as stools

    archives = stools.parse_archive_csv(args.input)  # parse archive names

    # Load model
    if args.model:

        # TODO: Check if loader_argv is set and check (if possible) loader_call if it receives arguments
        #       Print warning then if loader_argv is not set and print help message about custom models

        import importlib

        model_loader = importlib.import_module(args.model)  # import loader module
        loader_call = getattr(model_loader, 'load_model')  # import loader function

        # Parse loader arguments
        loader_argv = args.loader_argv

        # TODO: Improve parsing to support quotes and whitespaces inside said quotes
        #       Also parse whitespaces between argument and key
        argv_split = loader_argv.strip().split()
        argv_dict = {}

        for pair in argv_split:

            spl = pair.split('=')
            if len(spl) == 2:
                argv_dict[spl[0]] = spl[1]

        model = loader_call(**argv_dict)
    # TODO: Print loaded model info. Also add flag --inspect to print model summary.
    else:

        import utils.seismo_load as seismo_load

        if args.cnn:
            model = seismo_load.load_cnn(args.weights)
        elif args.favor:
            model = seismo_load.load_favor(args.weights)
        else:
            model = seismo_load.load_transformer(args.weights)

    # Main loop
    for n_archive, l_archives in enumerate(archives):

        # Read data
        streams = []
        for path in l_archives:
            streams.append(read(path))

        # If --plot-positives-original, save original streams
        original_streams = None
        if args.plot_positives_original:
            original_streams = []
            for path in l_archives:
                original_streams.append(read(path))

        # Pre-process data
        for st in streams:
            stools.pre_process_stream(st, args.no_filter, args.no_detrend)

        # Cut archives to the same length
        streams = stools.trim_streams(streams)
        if original_streams:
            original_streams = stools.trim_streams(original_streams)

        # Check if stream traces number is equal
        lengths = [len(st) for st in streams]
        if len(np.unique(np.array(lengths))) != 1:
            continue

        n_traces = len(streams[0])

        # Progress bar preparations
        total_batch_count = 0
        for i in range(n_traces):

            traces = [st[i] for st in streams]

            l_trace = traces[0].data.shape[0]
            last_batch = l_trace % args.batch_size
            batch_count = l_trace // args.batch_size + 1 \
                if last_batch \
                else l_trace // args.batch_size

            total_batch_count += batch_count

        # Predict
        current_batch_global = 0
        for i in range(n_traces):

            traces = stools.get_traces(streams, i)
            original_traces = None
            if original_streams:
                original_traces = stools.get_traces(original_streams, i)
                if traces[0].data.shape[0] != original_traces[0].data.shape[0]:
                    raise AttributeError('WARNING: Traces and original_traces have different sizes, '
                                         'check if preprocessing changes stream length!')

            # Determine batch count
            l_trace = traces[0].data.shape[0]
            last_batch = l_trace % args.batch_size
            batch_count = l_trace // args.batch_size + 1 \
                if last_batch \
                else l_trace // args.batch_size

            freq = traces[0].stats.sampling_rate

            for b in range(batch_count):

                detected_peaks = []

                b_size = args.batch_size
                if b == batch_count - 1 and last_batch:
                    b_size = last_batch

                start_pos = b * args.batch_size
                end_pos = start_pos + b_size
                t_start = traces[0].stats.starttime

                batches = [trace.slice(t_start + start_pos / freq, t_start + end_pos / freq) for trace in traces]
                original_batches = None
                if original_traces:
                    original_batches = [trace.slice(t_start + start_pos / freq, t_start + end_pos / freq)
                                        for trace in original_traces]

                # Progress bar
                stools.progress_bar(current_batch_global / total_batch_count, 40, add_space_around = False,
                                    prefix = f'Group {n_archive + 1} out of {len(archives)} [',
                                    postfix = f'] - Batch: {batches[0].stats.starttime} - {batches[0].stats.endtime}')
                current_batch_global += 1

                scores = stools.scan_traces(*batches,
                                            model = model,
                                            args = args,
                                            original_data = original_batches)  # predict

                if scores is None:
                    continue

                # TODO: window step 10 should be in params, including the one used in predict.scan_traces
                restored_scores = stools.restore_scores(scores, (len(batches[0]), len(model_labels)), 10)

                # Get indexes of predicted events
                predicted_labels = {}
                for label in positive_labels:

                    other_labels = []
                    for k in model_labels:
                        if k != label:
                            other_labels.append(model_labels[k])

                    positives = stools.get_positives(restored_scores,
                                                     positive_labels[label],
                                                     other_labels,
                                                     threshold = threshold_labels[label],)

                    predicted_labels[label] = positives

                # Convert indexes to datetime
                predicted_timestamps = {}
                for label in predicted_labels:

                    tmp_prediction_dates = []
                    for prediction in predicted_labels[label]:
                        starttime = batches[0].stats.starttime

                        # Get prediction UTCDateTime and model pseudo-probability
                        # TODO: why params['frequency'] here but freq = traces[0].stats.frequency before?
                        tmp_prediction_dates.append([starttime + (prediction[0] / frequency) + half_duration,
                                                     prediction[1]])

                    predicted_timestamps[label] = tmp_prediction_dates

                # Prepare output data
                for typ in predicted_timestamps:
                    for pred in predicted_timestamps[typ]:

                        prediction = {'type': typ,
                                      'datetime': pred[0],
                                      'pseudo-probability': pred[1]}

                        detected_peaks.append(prediction)

                stools.print_results(detected_peaks, args.out, precision = args.print_precision)

            print('')
