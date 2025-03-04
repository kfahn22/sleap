from pathlib import Path

import pytest

import sleap
from sleap.io.dataset import Labels
from sleap.nn.config.data import LabelsConfig
from sleap.nn.config.model import (
    CenteredInstanceConfmapsHeadConfig,
    CentroidsHeadConfig,
    MultiInstanceConfig,
    MultiInstanceConfmapsHeadConfig,
    PartAffinityFieldsHeadConfig,
    SingleInstanceConfmapsHeadConfig,
    UNetConfig,
)
from sleap.nn.config.training_job import TrainingJobConfig
from sleap.nn.training import (
    CentroidConfmapsModelTrainer,
    DataReaders,
    SingleInstanceModelTrainer,
    TopdownConfmapsModelTrainer,
    TopDownMultiClassModelTrainer,
    Trainer,
    create_trainer_using_cli as sleap_train,
)

sleap.use_cpu_only()


@pytest.fixture
def training_labels(min_labels):
    labels = min_labels
    labels.append(
        sleap.LabeledFrame(
            video=labels.videos[0], frame_idx=1, instances=labels[0].instances
        )
    )
    return labels


@pytest.fixture
def cfg():
    cfg = TrainingJobConfig()
    cfg.data.instance_cropping.center_on_part = "A"
    cfg.model.backbone.unet = UNetConfig(
        max_stride=8, output_stride=1, filters=8, filters_rate=1.0
    )
    cfg.optimization.preload_data = False
    cfg.optimization.batch_size = 1
    cfg.optimization.batches_per_epoch = 2
    cfg.optimization.epochs = 1
    cfg.outputs.save_outputs = False
    return cfg


def test_data_reader(min_labels_slp_path):
    data_readers = DataReaders.from_config(
        labels_config=LabelsConfig(validation_fraction=0.1),
        training=min_labels_slp_path,
        validation=None,
    )

    ex = next(iter(data_readers.training_labels_reader.make_dataset()))
    assert ex["image"].shape == (384, 384, 1)

    ex = next(iter(data_readers.validation_labels_reader.make_dataset()))
    assert ex["image"].shape == (384, 384, 1)

    # Test DataReaders using split_by_inds
    data_readers = DataReaders.from_config(
        labels_config=LabelsConfig(
            split_by_inds=True, validation_inds=[0], test_inds=[0], training_inds=[0]
        ),
        training=min_labels_slp_path,
        validation=None,
    )
    assert data_readers.training_labels_reader.example_indices == [0]
    assert data_readers.validation_labels_reader.example_indices == [0]
    assert data_readers.test_labels_reader.example_indices == [0]


def test_train_load_single_instance(
    min_labels_robot: Labels, cfg: TrainingJobConfig, tmp_path: str
):
    # set save directory
    cfg.outputs.run_name = "test_run"
    cfg.outputs.runs_folder = str(tmp_path / "training_runs")  # ensure it's a string
    cfg.outputs.save_outputs = True  # enable saving
    cfg.outputs.checkpointing.latest_model = True  # save latest model

    cfg.model.heads.single_instance = SingleInstanceConfmapsHeadConfig(
        sigma=1.5, output_stride=1, offset_refinement=False
    )
    trainer = SingleInstanceModelTrainer.from_config(
        cfg, training_labels=min_labels_robot
    )
    trainer.setup()
    trainer.train()

    # now load a new model and resume the checkpoint
    # set the model checkpoint folder
    cfg.model.base_checkpoint = cfg.outputs.run_path
    # unset save directory
    cfg.outputs.run_name = None
    cfg.outputs.runs_folder = None
    cfg.outputs.save_outputs = False  # disable saving
    cfg.outputs.checkpointing.latest_model = False  # disable saving latest model

    trainer2 = SingleInstanceModelTrainer.from_config(
        cfg, training_labels=min_labels_robot
    )
    trainer2.setup()

    # check the weights are the same
    for layer, layer2 in zip(trainer.keras_model.layers, trainer2.keras_model.layers):
        # grabbing the weights from the first model
        weights = layer.get_weights()
        # grabbing the weights from the second model
        weights2 = layer2.get_weights()
        # check the weights are the same
        for w, w2 in zip(weights, weights2):
            assert (w == w2).all()


def test_train_single_instance(min_labels_robot, cfg):
    cfg.model.heads.single_instance = SingleInstanceConfmapsHeadConfig(
        sigma=1.5, output_stride=1, offset_refinement=False
    )
    trainer = SingleInstanceModelTrainer.from_config(
        cfg, training_labels=min_labels_robot
    )
    trainer.setup()
    trainer.train()
    assert trainer.keras_model.output_names[0] == "SingleInstanceConfmapsHead"
    assert tuple(trainer.keras_model.outputs[0].shape) == (None, 320, 560, 2)


def test_train_single_instance_with_offset(min_labels_robot, cfg):
    cfg.model.heads.single_instance = SingleInstanceConfmapsHeadConfig(
        sigma=1.5, output_stride=1, offset_refinement=True
    )
    trainer = SingleInstanceModelTrainer.from_config(
        cfg, training_labels=min_labels_robot
    )
    trainer.setup()
    trainer.train()
    assert trainer.keras_model.output_names[0] == "SingleInstanceConfmapsHead"
    assert tuple(trainer.keras_model.outputs[0].shape) == (None, 320, 560, 2)

    assert trainer.keras_model.output_names[1] == "OffsetRefinementHead"
    assert tuple(trainer.keras_model.outputs[1].shape) == (None, 320, 560, 4)


def test_train_centroids(training_labels, cfg):
    cfg.model.heads.centroid = CentroidsHeadConfig(
        sigma=1.5, output_stride=1, offset_refinement=False
    )
    trainer = CentroidConfmapsModelTrainer.from_config(
        cfg, training_labels=training_labels
    )
    trainer.setup()
    trainer.train()
    assert trainer.keras_model.output_names[0] == "CentroidConfmapsHead"
    assert tuple(trainer.keras_model.outputs[0].shape) == (None, 384, 384, 1)


def test_train_centroids_with_offset(training_labels, cfg):
    cfg.model.heads.centroid = CentroidsHeadConfig(
        sigma=1.5, output_stride=1, offset_refinement=True
    )
    trainer = sleap.nn.training.CentroidConfmapsModelTrainer.from_config(
        cfg, training_labels=training_labels
    )
    trainer.setup()
    trainer.train()
    assert trainer.keras_model.output_names[0] == "CentroidConfmapsHead"
    assert trainer.keras_model.output_names[1] == "OffsetRefinementHead"
    assert tuple(trainer.keras_model.outputs[0].shape) == (None, 384, 384, 1)
    assert tuple(trainer.keras_model.outputs[1].shape) == (None, 384, 384, 2)


def test_train_topdown(training_labels, cfg):
    cfg.model.heads.centered_instance = CenteredInstanceConfmapsHeadConfig(
        sigma=1.5, output_stride=1, offset_refinement=False
    )
    trainer = TopdownConfmapsModelTrainer.from_config(
        cfg, training_labels=training_labels
    )
    trainer.setup()
    trainer.train()
    assert trainer.keras_model.output_names[0] == "CenteredInstanceConfmapsHead"
    assert tuple(trainer.keras_model.outputs[0].shape) == (None, 96, 96, 2)


def test_train_topdown_with_offset(training_labels, cfg):
    cfg.model.heads.centered_instance = CenteredInstanceConfmapsHeadConfig(
        sigma=1.5, output_stride=1, offset_refinement=True
    )
    trainer = TopdownConfmapsModelTrainer.from_config(
        cfg, training_labels=training_labels
    )
    trainer.setup()
    trainer.train()

    assert trainer.keras_model.output_names[0] == "CenteredInstanceConfmapsHead"
    assert trainer.keras_model.output_names[1] == "OffsetRefinementHead"
    assert tuple(trainer.keras_model.outputs[0].shape) == (None, 96, 96, 2)
    assert tuple(trainer.keras_model.outputs[1].shape) == (None, 96, 96, 4)


def test_train_bottomup(training_labels, cfg):
    cfg.model.heads.multi_instance = MultiInstanceConfig(
        confmaps=MultiInstanceConfmapsHeadConfig(
            output_stride=1, offset_refinement=False
        ),
        pafs=PartAffinityFieldsHeadConfig(output_stride=2),
    )
    trainer = TopdownConfmapsModelTrainer.from_config(
        cfg, training_labels=training_labels
    )
    trainer.setup()
    trainer.train()

    assert trainer.keras_model.output_names[0] == "MultiInstanceConfmapsHead"
    assert trainer.keras_model.output_names[1] == "PartAffinityFieldsHead"
    assert tuple(trainer.keras_model.outputs[0].shape) == (None, 384, 384, 2)
    assert tuple(trainer.keras_model.outputs[1].shape) == (None, 192, 192, 2)


def test_train_bottomup_with_offset(training_labels, cfg):
    cfg.model.heads.multi_instance = MultiInstanceConfig(
        confmaps=MultiInstanceConfmapsHeadConfig(
            output_stride=1, offset_refinement=True
        ),
        pafs=PartAffinityFieldsHeadConfig(output_stride=2),
    )
    trainer = TopdownConfmapsModelTrainer.from_config(
        cfg, training_labels=training_labels
    )
    trainer.setup()
    trainer.train()

    assert trainer.keras_model.output_names[0] == "MultiInstanceConfmapsHead"
    assert trainer.keras_model.output_names[1] == "PartAffinityFieldsHead"
    assert trainer.keras_model.output_names[2] == "OffsetRefinementHead"
    assert tuple(trainer.keras_model.outputs[0].shape) == (None, 384, 384, 2)
    assert tuple(trainer.keras_model.outputs[1].shape) == (None, 192, 192, 2)
    assert tuple(trainer.keras_model.outputs[2].shape) == (None, 384, 384, 4)


def test_train_bottomup_multiclass(min_tracks_2node_labels, cfg):
    labels = min_tracks_2node_labels
    cfg.data.preprocessing.input_scaling = 0.5
    cfg.model.heads.multi_class_bottomup = sleap.nn.config.MultiClassBottomUpConfig(
        confmaps=sleap.nn.config.MultiInstanceConfmapsHeadConfig(
            output_stride=2, offset_refinement=False
        ),
        class_maps=sleap.nn.config.ClassMapsHeadConfig(output_stride=2),
    )
    trainer = sleap.nn.training.BottomUpMultiClassModelTrainer.from_config(
        cfg, training_labels=labels
    )
    trainer.setup()
    trainer.train()

    assert trainer.keras_model.output_names[0] == "MultiInstanceConfmapsHead"
    assert trainer.keras_model.output_names[1] == "ClassMapsHead"
    assert tuple(trainer.keras_model.outputs[0].shape) == (None, 256, 256, 2)
    assert tuple(trainer.keras_model.outputs[1].shape) == (None, 256, 256, 2)


def test_train_topdown_multiclass(min_tracks_2node_labels, cfg):
    labels = min_tracks_2node_labels
    cfg.data.instance_cropping.center_on_part = "thorax"
    cfg.model.heads.multi_class_topdown = sleap.nn.config.MultiClassTopDownConfig(
        confmaps=sleap.nn.config.CenteredInstanceConfmapsHeadConfig(
            output_stride=1, offset_refinement=False, anchor_part="thorax"
        ),
        class_vectors=sleap.nn.config.ClassVectorsHeadConfig(output_stride=8),
    )
    trainer = sleap.nn.training.TopDownMultiClassModelTrainer.from_config(
        cfg, training_labels=labels
    )
    trainer.setup()
    trainer.train()

    assert trainer.keras_model.output_names[0] == "CenteredInstanceConfmapsHead"
    assert trainer.keras_model.output_names[1] == "ClassVectorsHead"
    assert tuple(trainer.keras_model.outputs[0].shape) == (None, 64, 64, 2)
    assert tuple(trainer.keras_model.outputs[1].shape) == (None, 2)


@pytest.mark.parametrize(
    "trainer_class", [TopdownConfmapsModelTrainer, TopDownMultiClassModelTrainer]
)
def test_train_cropping(
    training_labels: Labels, cfg: TrainingJobConfig, trainer_class: Trainer
):
    # Set model head
    cfg.model.heads.centered_instance = CenteredInstanceConfmapsHeadConfig(
        sigma=1.5, output_stride=1, offset_refinement=False
    )

    # Create trainer
    trainer = trainer_class.from_config(cfg, training_labels=training_labels)

    # Change trainer.config s.t. crop size not divisible by max stride
    trainer.config.data.instance_cropping.crop_size = trainer.model.maximum_stride + 1

    # Ensure crop size is updated to be divisible by max stride
    trainer._update_config()
    assert (
        trainer.config.data.instance_cropping.crop_size % trainer.model.maximum_stride
        == 0
    )


def test_resume_training_cli(
    min_single_instance_robot_model_path: str, small_robot_mp4_path: str, tmp_path: str
):
    """Test CLI to resume training."""

    base_checkpoint_path = min_single_instance_robot_model_path
    cfg = TrainingJobConfig.load_json(
        str(Path(base_checkpoint_path, "training_config.json"))
    )
    cfg.optimization.preload_data = False
    cfg.optimization.batch_size = 1
    cfg.optimization.batches_per_epoch = 2
    cfg.optimization.epochs = 1
    cfg.outputs.save_outputs = False

    # Save training config to tmp folder
    cfg_path = str(Path(tmp_path, "training_config.json"))
    cfg.save_json(cfg_path)

    # TODO (LM): Stop saving absolute paths in labels files!
    # We need to do this reload because we save absolute paths (for the video).
    labels_path = str(Path(base_checkpoint_path, "labels_gt.train.slp"))
    labels: Labels = sleap.load_file(labels_path, search_paths=[small_robot_mp4_path])
    labels_path = str(Path(tmp_path, "labels_gt.train.slp"))
    labels.save_file(labels, labels_path)

    # Run CLI to resume training
    trainer = sleap_train(
        [
            cfg_path,
            labels_path,
            "--base_checkpoint",
            base_checkpoint_path,
        ]
    )
    assert trainer.config.model.base_checkpoint == base_checkpoint_path

    # Run CLI without base checkpoint
    trainer = sleap_train([cfg_path, labels_path])
    assert trainer.config.model.base_checkpoint is None
