from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Union

from cwrap import BaseCClass
from ecl.ecl_util import EclFileEnum, get_file_type
from ecl.grid import EclGrid
from ecl.summary import EclSum

from ert import _clib
from ert._c_wrappers import ResPrototype
from ert._c_wrappers.config.rangestring import rangestring_to_list
from ert._c_wrappers.enkf import GenKwConfig
from ert._c_wrappers.enkf.config import EnkfConfigNode
from ert._c_wrappers.enkf.config.field_config import TRANSFORM_FUNCTIONS, Field
from ert._c_wrappers.enkf.config.parameter_config import ParameterConfig
from ert._c_wrappers.enkf.config.surface_config import SurfaceConfig
from ert._c_wrappers.enkf.config_keys import ConfigKeys
from ert._c_wrappers.enkf.enums import EnkfVarType, ErtImplType, GenDataFileType
from ert.parsing import ConfigValidationError, ConfigWarning

if TYPE_CHECKING:
    from ecl.util.util import StringList

logger = logging.getLogger(__name__)

ParameterConfiguration = List[Union[Field, SurfaceConfig, GenKwConfig]]


def _get_abs_path(file):
    if file is not None:
        file = os.path.realpath(file)
    return file


def _get_filename(file):
    if file is not None:
        file = os.path.basename(file)
    return file


def _option_dict(option_list: List[str], offset: int) -> Dict[str, str]:
    """Gets the list of options given to a keywords such as GEN_DATA.

    The first step of parsing will separate a line such as

      GEN_DATA NAME INPUT_FORMAT:ASCII RESULT_FILE:file.txt REPORT_STEPS:3

    into

    >>> opts = ["NAME", "INPUT_FORMAT:ASCII", "RESULT_FILE:file.txt", "REPORT_STEPS:3"]

    From there, _option_dict can be used to get a dictionary of the options:

    >>> _option_dict(opts, 1)
    {'INPUT_FORMAT': 'ASCII', 'RESULT_FILE': 'file.txt', 'REPORT_STEPS': '3'}

    Errors are reported to the log, and erroring fields ignored:

    >>> import sys
    >>> logger.addHandler(logging.StreamHandler(sys.stdout))
    >>> _option_dict(opts + [":T"], 1)
    Ignoring argument :T not properly formatted should be of type ARG:VAL
    {'INPUT_FORMAT': 'ASCII', 'RESULT_FILE': 'file.txt', 'REPORT_STEPS': '3'}

    """
    option_dict = {}
    for option_pair in option_list[offset:]:
        if not isinstance(option_pair, str):
            logger.warning(
                f"Ignoring unsupported option pair{option_pair} "
                f"of type {type(option_pair)}"
            )
            continue

        if len(option_pair.split(":")) == 2:
            key, val = option_pair.split(":")
            if val != "" and key != "":
                option_dict[key] = val
            else:
                logger.warning(
                    f"Ignoring argument {option_pair}"
                    " not properly formatted should be of type ARG:VAL"
                )
    return option_dict


def _str_to_bool(txt: str) -> bool:
    """This function converts text to boolean values according to the rules of
    the FORWARD_INIT keyword.

    The rules for str_to_bool is keep for backwards compatability

    First, any upper/lower case true/false value is converted to the corresponding
    boolean value:

    >>> _str_to_bool("TRUE")
    True
    >>> _str_to_bool("true")
    True
    >>> _str_to_bool("True")
    True
    >>> _str_to_bool("FALSE")
    False
    >>> _str_to_bool("false")
    False
    >>> _str_to_bool("False")
    False

    Any text which is not correctly identified as true or false returns False, but
    with a failure message written to the log:

    >>> _str_to_bool("fail")
    Failed to parse fail as bool! Using FORWARD_INIT:FALSE
    False
    """
    if txt.lower() == "true":
        return True
    elif txt.lower() == "false":
        return False
    else:
        logger.error(f"Failed to parse {txt} as bool! Using FORWARD_INIT:FALSE")
        return False


@dataclass
class ConfigNodeMeta:
    """Metadata Dataclass for EnkfConfigNode contained in EnsembleConfig"""

    key: str = ""
    forward_init: bool = False
    init_file: str = ""
    input_file: str = ""
    output_file: str = ""
    var_type: EnkfVarType = EnkfVarType.INVALID_VAR


class EnsembleConfig(BaseCClass):
    TYPE_NAME = "ens_config"
    _alloc_full = ResPrototype("void* ensemble_config_alloc_full(char*)", bind=False)
    _free = ResPrototype("void ensemble_config_free( ens_config )")
    _has_key = ResPrototype("bool ensemble_config_has_key( ens_config , char* )")
    _get_node = ResPrototype(
        "enkf_config_node_ref ensemble_config_get_node( ens_config , char*)"
    )
    _alloc_keylist = ResPrototype(
        "stringlist_obj ensemble_config_alloc_keylist( ens_config )"
    )
    _alloc_keylist_from_impl_type = ResPrototype(
        "stringlist_obj ensemble_config_alloc_keylist_from_impl_type(ens_config, \
                                                                     ert_impl_type_enum)"  # noqa
    )
    _add_node = ResPrototype(
        "void ensemble_config_add_node( ens_config , enkf_config_node )"
    )
    _add_summary_full = ResPrototype(
        "void ensemble_config_init_SUMMARY_full(ens_config, char*, ecl_sum)"
    )

    @staticmethod
    def _load_grid(grid_file: Optional[str]) -> Optional[EclGrid]:
        if grid_file is None:
            return None
        ecl_grid_file_types = [
            EclFileEnum.ECL_GRID_FILE,
            EclFileEnum.ECL_EGRID_FILE,
        ]
        if get_file_type(grid_file) not in ecl_grid_file_types:
            raise ValueError(f"grid file {grid_file} does not have expected type")
        return EclGrid.load_from_file(grid_file)

    @staticmethod
    def _load_refcase(refcase_file: Optional[str]) -> Optional[EclSum]:
        if refcase_file is None:
            return None

        refcase_filepath = Path(refcase_file)
        refcase_file = str(refcase_filepath.parent / refcase_filepath.stem)

        if not os.path.exists(refcase_file + ".UNSMRY"):
            raise ConfigValidationError(
                f"Cannot find UNSMRY file for refcase provided! {refcase_file}.UNSMRY"
            )

        if not os.path.exists(refcase_file + ".SMSPEC"):
            raise ConfigValidationError(
                f"Cannot find SMSPEC file for refcase provided! {refcase_file}.SMSPEC"
            )

        # defaults for loading refcase - necessary for using the function
        # exposed in python part of ecl
        refcase_load_args = {
            "load_case": refcase_file,
            "join_string": ":",
            "include_restart": True,
            "lazy_load": False,
            "file_options": 0,
        }
        return EclSum(**refcase_load_args)

    def __init__(
        self,
        grid_file: Optional[str] = None,
        ref_case_file: Optional[str] = None,
        tag_format: str = "<%s>",
        gen_data_list: Optional[List] = None,
        gen_kw_list: Optional[List] = None,
        surface_list: Optional[List] = None,
        summary_list: Optional[List] = None,
        schedule_file: Optional[List] = None,
        field_list=None,
    ):
        gen_kw_list = [] if gen_kw_list is None else gen_kw_list
        gen_data_list = [] if gen_data_list is None else gen_data_list
        surface_list = [] if surface_list is None else surface_list
        summary_list = [] if summary_list is None else summary_list
        schedule_file = [] if schedule_file is None else schedule_file
        field_list = [] if field_list is None else field_list

        self._grid_file = grid_file
        self._refcase_file = ref_case_file
        self.grid: Optional[EclGrid] = self._load_grid(grid_file)
        self.refcase: Optional[EclSum] = self._load_refcase(ref_case_file)
        self._gen_kw_tag_format = tag_format
        c_ptr = self._alloc_full(self._gen_kw_tag_format)
        self.py_nodes = {}

        self._config_node_meta: Dict[str, ConfigNodeMeta] = {}

        if c_ptr is None:
            raise ValueError("Failed to construct EnsembleConfig instance")
        super().__init__(c_ptr)

        for gene_data in gen_data_list:
            node = self.gen_data_node(gene_data)
            if node is not None:
                self._create_node_metainfo(gene_data, 1, EnkfVarType.DYNAMIC_RESULT)
                self.addNode(node)

        for gen_kw in gen_kw_list:
            gen_kw_node = self.gen_kw_node(gen_kw, tag_format)
            self._create_node_metainfo(gen_kw, 4, EnkfVarType.PARAMETER)
            self._config_node_meta[gen_kw[0]].output_file = gen_kw[2]
            init_file = self._config_node_meta[gen_kw[0]].init_file
            if init_file:
                self._config_node_meta[gen_kw[0]].init_file = os.path.abspath(init_file)
            self.addNode(gen_kw_node)

        for surface in surface_list:
            surface_node = self.get_surface_node(surface)
            self._create_node_metainfo(surface, 1, EnkfVarType.PARAMETER)
            self.addNode(surface_node)

        for key in summary_list:
            if isinstance(key, list):
                for kkey in key:
                    self.add_summary_full(kkey, self.refcase)
            else:
                self.add_summary_full(key, self.refcase)

        for field in field_list:
            if self.grid is None:
                raise ConfigValidationError(
                    "In order to use the FIELD keyword, a GRID must be supplied."
                )
            field_node = self.get_field_node(field, self.grid, grid_file)
            self._create_node_metainfo(field, 2)
            self._storeFieldMetaInfo(field)
            self.addNode(field_node)

        if schedule_file:
            schedule_file_node = self._get_schedule_file_node(
                schedule_file, self._gen_kw_tag_format
            )
            self._config_node_meta[ConfigKeys.PRED_KEY] = ConfigNodeMeta(
                key=ConfigKeys.PRED_KEY,
                var_type=EnkfVarType.PARAMETER,
                output_file=_get_filename(_get_abs_path(schedule_file[0])),
            )
            self.addNode(schedule_file_node)

    @staticmethod
    def gen_data_node(gen_data: List[str]) -> Optional[EnkfConfigNode]:
        options = _option_dict(gen_data, 1)
        name = gen_data[0]
        res_file = options.get(ConfigKeys.RESULT_FILE)
        if res_file is None:
            raise ConfigValidationError(
                f"Missing or unsupported RESULT_FILE for GEN_DATA key {name!r}"
            )
        input_format_str = options.get(ConfigKeys.INPUT_FORMAT)
        if input_format_str != "ASCII":
            warnings.warn(
                f"Missing or unsupported GEN_DATA INPUT_FORMAT for key {name!r}. "
                f"Assuming INPUT_FORMAT is ASCII.",
                category=ConfigWarning,
            )
        report_steps_str = options.get(ConfigKeys.REPORT_STEPS, "")
        report_steps = rangestring_to_list(report_steps_str)

        return EnkfConfigNode.create_gen_data_full(
            name,
            res_file,
            GenDataFileType.ASCII,
            report_steps,
        )

    def add_config_node_meta(
        self,
        key: str = "",
        forward_init: bool = False,
        init_file: str = "",
        input_file: str = "",
        output_file: str = "",
        var_type: Optional[EnkfVarType] = EnkfVarType.INVALID_VAR,
    ):
        metaInfo = ConfigNodeMeta(
            key, forward_init, init_file, input_file, output_file, var_type
        )
        self._config_node_meta[key] = metaInfo

    def _create_node_metainfo(
        self,
        keywords: Union[dict, list],
        offset: int,
        var_type: EnkfVarType = EnkfVarType.INVALID_VAR,
    ):
        options = _option_dict(keywords, offset)
        key = keywords[0]
        forward_init = _str_to_bool(options.get(ConfigKeys.FORWARD_INIT, "FALSE"))
        init_file = options.get(ConfigKeys.INIT_FILES, "")
        input_file = options.get(ConfigKeys.RESULT_FILE, "")
        output_file = options.get("OUTPUT_FILE", "")

        self.add_config_node_meta(
            key=key,
            forward_init=forward_init,
            init_file=init_file,
            input_file=input_file,
            output_file=output_file,
            var_type=var_type,
        )

    def _storeFieldMetaInfo(self, node_kw: Union[dict, list]):
        name = node_kw[0]
        var_type_string = node_kw[1]
        out_file = node_kw[2]
        var_type = EnkfVarType.INVALID_VAR

        if var_type_string == ConfigKeys.PARAMETER_KEY:
            var_type = EnkfVarType.PARAMETER

        self._config_node_meta[name].output_file = out_file
        self._config_node_meta[name].var_type = var_type

    @staticmethod
    def gen_kw_node(gen_kw: List[str], tag_format: str) -> EnkfConfigNode:
        name = gen_kw[0]
        tmpl_path = _get_abs_path(gen_kw[1])
        param_file_path = _get_abs_path(gen_kw[3])
        return EnkfConfigNode.create_gen_kw(
            name,
            tmpl_path,
            param_file_path,
            tag_format,
        )

    @staticmethod
    def get_surface_node(surface: List[str]) -> SurfaceConfig:
        options = _option_dict(surface, 1)
        name = surface[0]
        init_file = options.get(ConfigKeys.INIT_FILES)
        out_file = options.get("OUTPUT_FILE")
        base_surface = options.get(ConfigKeys.BASE_SURFACE_KEY)
        forward_init = _str_to_bool(options.get(ConfigKeys.FORWARD_INIT, "FALSE"))
        errors = []
        if not out_file:
            errors.append("Missing required OUTPUT_FILE")
        if not init_file:
            errors.append("Missing required INIT_FILES")
        elif not forward_init:
            if "%d" not in init_file:
                errors.append("Must give file name with %d with FORWARD_INIT:FALSE")
        if not base_surface:
            errors.append("Missing required BASE_SURFACE")
        elif not Path(base_surface).exists():
            errors.append(f"BASE_SURFACE:{base_surface} not found")
        if errors:
            errors = "\n".join(errors)
            raise ConfigValidationError(
                f"SURFACE {name} incorrectly configured: {errors}"
            )

        return SurfaceConfig(
            name=name,
            forward_init=forward_init,
            forward_init_file=init_file,
            output_file=Path(out_file),
            base_surface_path=base_surface,
        )

    @staticmethod
    def get_field_node(
        field: Union[dict, list], grid: EclGrid, grid_file: str
    ) -> Field:
        name = field[0]
        out_file = Path(field[2])
        options = _option_dict(field, 2)
        init_transform = options.get(ConfigKeys.INIT_TRANSFORM)
        forward_init = _str_to_bool(options.get(ConfigKeys.FORWARD_INIT, "FALSE"))
        output_transform = options.get(ConfigKeys.OUTPUT_TRANSFORM)
        input_transform = options.get(ConfigKeys.INPUT_TRANSFORM)
        min_ = options.get(ConfigKeys.MIN_KEY)
        max_ = options.get(ConfigKeys.MAX_KEY)
        init_files = options.get(ConfigKeys.INIT_FILES)

        if input_transform:
            warnings.warn(
                f"Got INPUT_TRANSFORM for FIELD: {name}, "
                f"this has no effect and can be removed",
                category=ConfigWarning,
            )
        if init_transform and init_transform not in TRANSFORM_FUNCTIONS:
            raise ValueError(
                f"FIELD INIT_TRANSFORM:{init_transform} is an invalid function"
            )
        if output_transform and output_transform not in TRANSFORM_FUNCTIONS:
            raise ValueError(
                f"FIELD OUTPUT_TRANSFORM:{output_transform} is an invalid function"
            )

        if min_ is not None and not isinstance(min_, float):
            min_ = float(min_)
        if max_ is not None and not isinstance(max_, float):
            max_ = float(max_)
        return Field(
            name=name,
            nx=grid.nx,
            ny=grid.ny,
            nz=grid.nz,
            file_format=out_file.suffix[1:],
            output_transformation=output_transform,
            input_transformation=init_transform,
            truncation_max=max_,
            truncation_min=min_,
            forward_init=forward_init,
            forward_init_file=init_files,
            output_file=out_file,
            grid_file=grid_file,
        )

    @staticmethod
    def _get_schedule_file_node(
        schedule_file: Union[dict, list], tag_format: str
    ) -> EnkfConfigNode:
        file_path = _get_abs_path(schedule_file[0])
        options = _option_dict(schedule_file, 1)
        parameter = options.get(ConfigKeys.PARAMETER_KEY)

        return EnkfConfigNode.create_gen_kw(
            ConfigKeys.PRED_KEY,
            file_path,
            parameter,
            tag_format,
        )

    @classmethod
    def from_dict(cls, config_dict) -> EnsembleConfig:
        grid_file_path = _get_abs_path(config_dict.get(ConfigKeys.GRID))
        refcase_file_path = _get_abs_path(config_dict.get(ConfigKeys.REFCASE))
        tag_format = config_dict.get(ConfigKeys.GEN_KW_TAG_FORMAT, "<%s>")
        gen_data_list = config_dict.get(ConfigKeys.GEN_DATA, [])
        gen_kw_list = config_dict.get(ConfigKeys.GEN_KW, [])
        surface_list = config_dict.get(ConfigKeys.SURFACE_KEY, [])
        summary_list = config_dict.get(ConfigKeys.SUMMARY, [])
        schedule_file = config_dict.get(ConfigKeys.SCHEDULE_PREDICTION_FILE, [])
        field_list = config_dict.get(ConfigKeys.FIELD_KEY, [])

        ens_config = cls(
            grid_file=grid_file_path,
            ref_case_file=refcase_file_path,
            tag_format=tag_format,
            gen_data_list=gen_data_list,
            gen_kw_list=gen_kw_list,
            surface_list=surface_list,
            summary_list=summary_list,
            schedule_file=schedule_file,
            field_list=field_list,
        )

        return ens_config

    def _node_info(self, node: str) -> str:
        impl_type = ErtImplType.from_string(node)
        key_list = self.getKeylistFromImplType(impl_type)
        return f"{node}: " f"{[self.getNode(key) for key in key_list]}, "

    def __repr__(self):
        if not self._address():
            return "<EnsembleConfig()>"
        return (
            "EnsembleConfig(config_dict={"
            + self._node_info(ConfigKeys.GEN_KW)
            + self._node_info(ConfigKeys.GEN_DATA)
            + self._node_info(ConfigKeys.SURFACE_KEY)
            + self._node_info(ConfigKeys.SUMMARY)
            + self._node_info(ConfigKeys.FIELD_KEY)
            + f"{ConfigKeys.GRID}: {self._grid_file},"
            + f"{ConfigKeys.REFCASE}: {self._refcase_file}"
            + "}"
        )

    def __getitem__(self, key: str) -> EnkfConfigNode:
        if key in self:
            node = self._get_node(key).setParent(self)
            if node.getImplementationType() == ErtImplType.GEN_DATA:
                node.input_file = self._config_node_meta[key].input_file
            elif node.getImplementationType() == ErtImplType.SUMMARY:
                pass
            else:
                node.forward_init_file = self._config_node_meta[key].init_file
                node.forward_init = self._config_node_meta[key].forward_init
                node.output_file = self._config_node_meta[key].output_file

            return node
        elif key in self.py_nodes:
            return self.py_nodes[key]
        else:
            raise KeyError(f"The key:{key} is not in the ensemble configuration")

    def getNode(self, key: str) -> EnkfConfigNode:
        return self[key]

    def alloc_keylist(self) -> StringList:
        return self._alloc_keylist()

    def add_summary_full(self, key, refcase) -> EnkfConfigNode:
        self._create_node_metainfo([key], 0, EnkfVarType.DYNAMIC_RESULT)
        return self._add_summary_full(key, refcase)

    def _check_config_node(self, node: EnkfConfigNode):
        mode_config = node.getModelConfig()
        errors = []

        def _check_non_negative_parameter(param: str) -> Optional[str]:
            key = prior["key"]
            dist = prior["function"]
            param_val = prior["parameters"][param]
            if param_val < 0:
                errors.append(
                    f"Negative {param} {param_val!r}"
                    f" for {dist} distributed parameter {key!r}"
                )

        for prior in mode_config.get_priors():
            if prior["function"] == "LOGNORMAL":
                _check_non_negative_parameter("MEAN")
                _check_non_negative_parameter("STD")
            elif prior["function"] in ["NORMAL", "TRUNCATED_NORMAL"]:
                _check_non_negative_parameter("STD")
        if errors:
            raise ConfigValidationError(
                config_file=mode_config.getParameterFile(),
                errors=errors,
            )

    def addNode(self, config_node: Union[EnkfConfigNode, Field]):
        assert config_node is not None
        key = config_node.getKey()
        if key in self:
            raise ConfigValidationError(
                f"Enkf config node with key {key!r} already present in ensemble config"
            )
        if isinstance(config_node, EnkfConfigNode):
            if config_node.getImplementationType() == ErtImplType.GEN_KW:
                self._check_config_node(config_node)
            self._add_node(config_node)
            config_node.convertToCReference(self)
        else:
            self.py_nodes[config_node.name] = config_node

    def getKeylistFromVarType(self, var_mask: EnkfVarType) -> List[str]:
        assert isinstance(var_mask, EnkfVarType)

        keylist = []
        for k, v in self._config_node_meta.items():
            if int(v.var_type) & int(var_mask):
                keylist.append(k)

        return keylist

    def getKeylistFromImplType(self, ert_impl_type) -> List[str]:
        assert isinstance(ert_impl_type, ErtImplType)
        return list(self._alloc_keylist_from_impl_type(ert_impl_type))

    @property
    def grid_file(self) -> Optional[str]:
        return self._grid_file

    @property
    def get_refcase_file(self) -> Optional[str]:
        return self._refcase_file

    @property
    def parameters(self) -> List[str]:
        return self.getKeylistFromVarType(
            EnkfVarType.PARAMETER + EnkfVarType.EXT_PARAMETER
        )

    def __contains__(self, key):
        return self._has_key(key)

    def free(self):
        self._free()

    def __eq__(self, other):
        self_param_list = set(self.alloc_keylist())
        other_param_list = set(other.alloc_keylist())
        if self_param_list != other_param_list:
            return False

        for a in self_param_list:
            if a in self and a in other:
                if self.getNode(a) != other.getNode(a):
                    return False
            else:
                return False

        if (
            self._grid_file != other._grid_file
            or self._refcase_file != other._refcase_file
        ):
            return False

        return True

    def __ne__(self, other):
        return not self == other

    def getMetaInfo(self, key: str) -> Optional[ConfigNodeMeta]:
        if key in self._config_node_meta:
            return self._config_node_meta[key]
        return None

    def getUseForwardInit(self, key) -> bool:
        metaInfo = self.getMetaInfo(key)
        return metaInfo.forward_init if metaInfo else False

    def get_var_type(self, key) -> EnkfVarType:
        metaInfo = self.getMetaInfo(key)
        return metaInfo.var_type if metaInfo else EnkfVarType.INVALID_VAR

    def get_summary_keys(self) -> List[str]:
        return _clib.ensemble_config.get_summary_keys(self)

    @property
    def parameter_configuration(self) -> ParameterConfiguration:
        parameter_configs = []
        for parameter in self.parameters:
            config_node = self.getNode(parameter)
            config_type = config_node.getImplementationType()
            if config_type == ErtImplType.GEN_KW:
                node = config_node.getKeywordModelConfig()
                node.forward_init_file = self._config_node_meta[parameter].init_file
                node.forward_init = self._config_node_meta[parameter].forward_init
                node.output_file = self._config_node_meta[parameter].output_file
                parameter_configs.append(node)
            elif isinstance(config_node, ParameterConfig):
                parameter_configs.append(config_node)
            elif config_type == ErtImplType.EXT_PARAM:
                node = config_node.getModelConfig()
                node.forward_init = self._config_node_meta[parameter].init_file
                parameter_configs.append(node)

        return parameter_configs
