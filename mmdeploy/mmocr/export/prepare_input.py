from typing import Any, Optional, Sequence, Union

import mmcv
import numpy as np
from mmcv.parallel import collate, scatter
from mmdet.datasets import replace_ImageToTensor
from mmocr.datasets import build_dataloader as build_dataloader_mmocr
from mmocr.datasets import build_dataset as build_dataset_mmocr

from mmdeploy.utils import Task, load_config


def create_input(task: Task,
                 model_cfg: Union[str, mmcv.Config],
                 imgs: Any,
                 input_shape: Sequence[int] = None,
                 device: str = 'cuda:0'):
    if isinstance(imgs, (list, tuple)):
        if not isinstance(imgs[0], (np.ndarray, str)):
            raise AssertionError('imgs must be strings or numpy arrays')

    elif isinstance(imgs, (np.ndarray, str)):
        imgs = [imgs]
    else:
        raise AssertionError('imgs must be strings or numpy arrays')

    if model_cfg.data.test['type'] == 'ConcatDataset':
        model_cfg.data.test.pipeline = \
            model_cfg.data.test['datasets'][0].pipeline

    is_ndarray = isinstance(imgs[0], np.ndarray)

    if is_ndarray:
        model_cfg = model_cfg.copy()
        # set loading pipeline type
        model_cfg.data.test.pipeline[0].type = 'LoadImageFromNdarray'

    model_cfg.data.test.pipeline = replace_ImageToTensor(
        model_cfg.data.test.pipeline)
    # for static exporting
    if input_shape is not None:
        if task == Task.TEXT_DETECTION:
            model_cfg.data.test.pipeline[1].img_scale = tuple(input_shape)
            model_cfg.data.test.pipeline[1].transforms[0].keep_ratio = False
            model_cfg.data.test.pipeline[1].transforms[0].img_scale = tuple(
                input_shape)
        elif task == Task.TEXT_RECOGNITION:
            resize = {
                'height': input_shape[0],
                'min_width': input_shape[1],
                'max_width': input_shape[1],
                'keep_aspect_ratio': False
            }
            model_cfg.data.test.pipeline[1].update(resize)
    from mmdet.datasets.pipelines import Compose
    from mmocr.datasets import build_dataset  # noqa: F401
    test_pipeline = Compose(model_cfg.data.test.pipeline)

    datas = []
    for img in imgs:
        # prepare data
        if is_ndarray:
            # directly add img
            data = dict(img=img)
        else:
            # add information into dict
            data = dict(img_info=dict(filename=img), img_prefix=None)

        # build the data pipeline
        data = test_pipeline(data)
        # get tensor from list to stack for batch mode (text detection)
        datas.append(data)

    if isinstance(datas[0]['img'], list) and len(datas) > 1:
        raise Exception('aug test does not support '
                        f'inference with batch size '
                        f'{len(datas)}')

    data = collate(datas, samples_per_gpu=len(imgs))

    # process img_metas
    if isinstance(data['img_metas'], list):
        data['img_metas'] = [
            img_metas.data[0] for img_metas in data['img_metas']
        ]
    else:
        data['img_metas'] = data['img_metas'].data

    if isinstance(data['img'], list):
        data['img'] = [img.data for img in data['img']]
        if isinstance(data['img'][0], list):
            data['img'] = [img[0] for img in data['img']]
    else:
        data['img'] = data['img'].data

    if device != 'cpu':
        data = scatter(data, [device])[0]

    return data, data['img']


def build_dataset(dataset_cfg: Union[str, mmcv.Config],
                  dataset_type: str = 'val',
                  **kwargs):
    dataset_cfg = load_config(dataset_cfg)[0].copy()

    data = dataset_cfg.data
    assert dataset_type in data
    dataset = build_dataset_mmocr(data[dataset_type])

    return dataset


def build_dataloader(dataset,
                     samples_per_gpu: int,
                     workers_per_gpu: int,
                     num_gpus: int = 1,
                     dist: bool = False,
                     shuffle: bool = False,
                     seed: Optional[int] = None,
                     **kwargs):
    return build_dataloader_mmocr(
        dataset,
        samples_per_gpu,
        workers_per_gpu,
        num_gpus=num_gpus,
        dist=dist,
        shuffle=shuffle,
        seed=seed,
        **kwargs)


def get_tensor_from_input(input_data):
    return input_data['img']