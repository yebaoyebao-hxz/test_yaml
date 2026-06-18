from common.setting import ensure_path
from utils.other_tools.models import Config
from utils.read_files_tools.yaml_control import GetYamlData

_data = GetYamlData(ensure_path("\\common\\config.yaml")).get_yaml_data()
config = Config(**_data)