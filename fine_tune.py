"""
File: fine_tune.py
Author: Andrey Stepnov
Email: myjamm@gmail.com
Github: https://github.com/jamm1985
Description: example of fine tuning parameters of pre-trained model on specific datasets
"""

import tensorflow as tf
from tensorflow import keras
from seismo_transformer import load_test_train_data, seismo_transformer

# compose the model
model = seismo_transformer(
    maxlen=400,
    patch_size=25,
    num_channels=3,
    d_model=48,
    num_heads=8,
    ff_dim_factor=4,
    layers_depth=8,
    num_classes=3,
    drop_out_rate=0.1)

# load pre-trained weights
model.load_weights('WEIGHTS/model.240K.V1.h5')

# fix transformer blocks
for i in range(8,16,1):
    model.layers[i].trainable = False

model.summary()

# compile the model
LR = 0.001
model.compile(
    optimizer=keras.optimizers.Adam(learning_rate=LR),
    loss=keras.losses.SparseCategoricalCrossentropy(),
    metrics=[keras.metrics.SparseCategoricalAccuracy()],)


# load Sakhalin test data M1.0+ fixed channel order
X_train_sakh, X_test_sakh, y_train_sakh, y_test_sakh =\
    load_test_train_data('DATA/2020-09-10-SAKHALIN_1_FIXED.hdf5', 0.25)

print("Fine-tune model on Sakhalin data")
history = model.fit(
    X_train_sakh,
    y_train_sakh,
    batch_size=64,
    epochs=50,
    validation_data=(X_test_sakh, y_test_sakh),
)

# load Dagestan test data M1.0+ fixed channel order
X_train_dag, X_test_dag, y_train_dag, y_test_dag =\
    load_test_train_data('DATA/2020-09-10-DAGESTAN_1_FIXED.hdf5', 0.25)

print("Fine-tune model on Dagestan data")
history = model.fit(
    X_train_dag,
    y_train_dag,
    batch_size=64,
    epochs=50,
    validation_data=(X_test_dag, y_test_dag),
)