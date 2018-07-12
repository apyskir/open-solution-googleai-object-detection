from functools import partial

from steppy.base import IdentityOperation
from steppy.adapter import Adapter, E

from .loaders import ImageDetectionLoader
from .steppy.base import Step
from .models import Retina
from .retinanet import DataDecoder
from .postprocessing import SubmissionProducer, resize_bboxes
from .utils import make_apply_transformer, get_image_size
from .preprocessing import GoogleAiLabelEncoder, GoogleAiLabelDecoder


def retinanet(config, train_mode):
    persist_output = False
    load_persisted_output = False

    loader, label_encoder = preprocessing_generator(config, is_train=train_mode)

    retinanet = Step(name='retinanet',
                     transformer=Retina(**config.retinanet, train_mode=train_mode),
                     input_steps=[loader],
                     experiment_directory=config.env.cache_dirpath,
                     persist_output=persist_output,
                     is_trainable=True,
                     load_persisted_output=load_persisted_output)

    if train_mode:
        return retinanet

    postprocessor = postprocessing(retinanet, label_encoder, config)

    output = Step(name='output',
                  transformer=IdentityOperation(),
                  input_steps=[postprocessor],
                  adapter=Adapter({'y_pred': E(postprocessor.name, 'postprocessed_images')}),
                  experiment_directory=config.env.cache_dirpath,
                  persist_output=persist_output,
                  load_persisted_output=load_persisted_output)
    return output


def preprocessing_generator(config, is_train):
    label_encoder = Step(name='label_encoder',
                         transformer=GoogleAiLabelEncoder(**config.label_encoder),
                         input_data=['metadata'],
                         adapter=Adapter({'annotations': E('metadata', 'annotations'),
                                          'annotations_human_labels': E('metadata', 'annotations_human_labels')
                                          }),
                         is_trainable=True,
                         experiment_directory=config.env.cache_dirpath)

    if is_train:
        loader = Step(name='loader',
                      transformer=ImageDetectionLoader(train_mode=True, **config.loader),
                      input_data=['input', 'validation_input'],
                      input_steps=[label_encoder],
                      adapter=Adapter({'ids': E('input', 'img_ids'),
                                       'valid_ids': E('validation_input', 'valid_img_ids'),
                                       'annotations': E(label_encoder.name, 'annotations'),
                                       'annotations_human_labels': E(label_encoder.name, 'annotations_human_labels'),
                                       }),
                      experiment_directory=config.env.cache_dirpath)

    else:
        loader = Step(name='loader',
                      transformer=ImageDetectionLoader(train_mode=False, **config.loader),
                      input_data=['specs'],
                      input_steps=[label_encoder],
                      adapter=Adapter({'ids': E('input', 'img_ids'),
                                       'annotations': None,
                                       'annotations_human_labels': None,
                                       }),
                      experiment_directory=config.env.cache_dirpath)
    return loader, label_encoder


def postprocessing(model, label_encoder, config):
    label_decoder = Step(name='label_decoder',
                         transformer=GoogleAiLabelDecoder(label_encoder.transformer),
                         input_steps=[model],
                         experiment_directory=config.env.cache_dirpath)

    decoder = Step(name='decoder',
                   transformer=DataDecoder(),
                   input_steps=[model, ],
                   experiment_directory=config.env.cache_dirpath)

    resizer = Step(name='resizer',
                   transformer=make_apply_transformer(func=resize_bboxes,
                                                      output_name='resized_results',
                                                      ),
                   input_steps=[decoder, ],
                   experiment_directory=config.env.cache_dirpath)

    submission_producer = Step(name='submission_producer',
                               transformer=SubmissionProducer(),
                               input_steps=[resizer, label_decoder],
                               input_data=['input', ],
                               adapter={'image_ids': ([('input', 'img_ids')]),
                                        'results': ([(resizer.name, 'results')]),
                                        'image_size': ([('input', 'image_size')]),
                                        'decoder_dict': ([(label_decoder.name, 'dict')])},
                               experiment_directory=config.env.cache_dirpath)
    return submission_producer


PIPELINES = {'retinanet': {'train': partial(retinanet, train_mode=True),
                           'inference': partial(retinanet, train_mode=False),
                           },
             }
