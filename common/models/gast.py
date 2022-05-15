import tensorflow as tf
import tensorflow.keras as keras
import settransformer as st
from . import CustomModel
from .. core.custom_objects import CustomObject
from .. layers import SampleSet

@CustomObject
class GastGenerator(CustomModel):
	"""
	A generic generator model based on the GAST framework.
	"""
	def __init__(
		self,
		max_set_size,
		noise_dim,
		embed_dim,
		latent_dim,
		stack,
		num_heads,
		num_anchors,
		use_keras_mha=False,
		use_spectral_norm=True,
		activation="relu",
		cond_dim=None,
		ff_dim=None,
		mlp_dim=None,
		pre_layernorm=True,
		include_class=False,
		num_classes=None,
		class_dim=None,
		**kwargs
	):
		super().__init__(**kwargs)
		self.max_set_size = max_set_size
		self.noise_dim = noise_dim
		self.embed_dim = embed_dim
		self.latent_dim = latent_dim
		self.stack = stack
		self.num_heads = num_heads
		self.num_anchors = num_anchors
		self.use_keras_mha = use_keras_mha
		self.use_spectral_norm = use_spectral_norm
		self.activation = activation
		self.cond_dim = cond_dim if cond_dim is not None else embed_dim
		self.ff_dim = ff_dim
		self.mlp_dim = mlp_dim if mlp_dim is not None else self.ff_dim
		self.pre_layernorm = pre_layernorm
		self.include_class = include_class
		self.num_classes = num_classes
		self.class_dim = class_dim if class_dim is not None else noise_dim
		self.model = self.build_model()

	def build_model(self):
		# Inputs
		noise = keras.layers.Input((self.noise_dim,), name="noise")
		cardinality = keras.layers.Input((1,), dtype=tf.int32, name="cardinality")
		if self.include_class:
			label = keras.layers.Input((1,), dtype=tf.int32, name="label")

		# Conditioning representation
		condition = noise
		if self.include_class:
			condition = keras.layers.Embedding(self.num_samples, self.class_dim)(label)
			condition = keras.layers.Flatten()(condition)
			condition = keras.layers.Concatenate()((noise, condition))
		condition = keras.layers.Dense(self.cond_dim, activation=self.activation)(condition)

		# Conditioned sample set
		y = SampleSet(self.max_set_size, self.embed_dim)(cardinality)
		for i in range(self.stack):
			y1 = st.ConditionedSetAttentionBlock(
				embed_dim=self.latent_dim,
				num_heads=self.num_heads,
				num_anchors=self.num_anchors,
				ff_dim=self.ff_dim,
				ff_activation=self.activation,
				use_keras_mha=self.use_keras_mha,
				use_spectral_norm=self.use_spectral_norm,
				prelayernorm=self.pre_layernorm,
				is_final=(i == self.stack - 1))(y, condition)
			y = keras.layers.Add()((y, y1))
		y = st.spectral_dense(self.latent_dim, use_spectral_norm=self.use_spectral_norm)(y)

		if self.include_class:
			return keras.Model((noise, label, cardinality), y)
		return keras.Model((noise, cardinality), y)

	def call(self, inputs, training=None):
		return self.model(inputs, training=training)

	def get_config(self):
		config = super().get_config()
		config.update({
			"max_set_size": self.max_set_size,
			"noise_dim": self.noise_dim,
			"embed_dim": self.embed_dim,
			"latent_dim": self.latent_dim,
			"stack": self.stack,
			"num_heads": self.num_heads,
			"num_anchors": self.num_anchors,
			"use_keras_mha": self.use_keras_mha,
			"use_spectral_norm": self.use_spectral_norm,
			"activation": self.activation,
			"cond_dim": self.cond_dim,
			"ff_dim": self.ff_dim,
			"mlp_dim": self.mlp_dim,
			"pre_layernorm": self.pre_layernorm,
			"include_class": self.include_class,
			"num_classes": self.num_classes,
			"class_dim": self.class_dim
		})
		return config


@CustomObject
class GastDiscriminator(CustomModel):
	def __init__(
		self,
		latent_dim,
		embed_dim,
		stack,
		num_heads,
		num_anchors,
		use_keras_mha=False,
		use_spectral_norm=True,
		activation="relu",
		ff_dim=None,
		pre_layernorm=True,
		num_classes=1,
		**kwargs
	):
		super().__init__(**kwargs)
		self.latent_dim = latent_dim
		self.embed_dim = embed_dim
		self.stack = stack
		self.num_heads = num_heads
		self.num_anchors = num_anchors
		self.use_keras_mha = use_keras_mha
		self.use_spectral_norm = use_spectral_norm
		self.activation = activation
		self.ff_dim = ff_dim
		self.pre_layernorm = pre_layernorm
		self.num_classes = num_classes

		self.model = self.build_model()

	def build_model(self):
		y = x = keras.layers.Input((None, self.latent_dim))

		y = keras.layers.Dense(self.embed_dim)(y)

		# Encode the original set
		enc = [st.InducedSetEncoder(
			num_seeds=1,
			embed_dim=self.embed_dim,
			num_heads=self.num_heads,

			ff_dim=self.ff_dim,
			ff_activation=self.activation,
			prelayernorm=self.pre_layernorm,
			is_final=True,
			use_keras_mha=self.use_keras_mha,
			use_spectral_norm=self.use_spectral_norm)(y)]

		# Pass the set through ISABs, encoding along the way
		for i in range(self.stack):
			y1 = st.InducedSetAttentionBlock(
				embed_dim=self.embed_dim,
				num_heads=self.num_heads,
				num_induce=self.num_anchors,
				ff_dim=self.ff_dim,
				ff_activation=self.activation,
				use_keras_mha=self.use_keras_mha,
				use_spectral_norm=self.use_spectral_norm,
				prelayernorm=self.pre_layernorm,
				is_final=(i == self.stack - 1))(y)
			y = keras.layers.Add()((y, y1))
			enc.append(st.InducedSetEncoder(
				num_seeds=1,
				embed_dim=self.embed_dim,
				num_heads=self.num_heads,
				ff_dim=self.ff_dim,
				ff_activation=self.activation,
				prelayernorm=self.pre_layernorm,
				is_final=True,
				use_keras_mha=self.use_keras_mha,
				use_spectral_norm=self.use_spectral_norm)(y))

		y = keras.layers.Concatenate()(enc)
		# y = keras.layers.Dense(LATENT_DIM, activation=self.activation)(y)
		y = keras.layers.Dense(self.num_classes + 1, activation="softmax")(y)

		return keras.Model(x, y)

	def call(self, inputs, training=None):
		return self.model(inputs, training)