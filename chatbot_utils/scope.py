import os
from typing import List

import yaml

from .github import refresh
from .scope_models import Dialog, parse_yaml_to_dialog


RBHR_MAIA_GITHUB_REPO_URL = "https://code.rbi.tech/raiffeisen/maia-bot-rbhr-raia"


def load_dialogs_from_dir(dialogs_dir: str) -> List[Dialog]:
    dialogs: List[Dialog] = []

    for root, _, files in os.walk(dialogs_dir):
        for file in files:
            if file.endswith(".yaml") or file.endswith(".yml"):
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    try:
                        dialog_data = yaml.safe_load(f)
                        dialog = parse_yaml_to_dialog(dialog_data)
                        dialogs.append(dialog)
                    except yaml.YAMLError as e:
                        print(f"Error parsing YAML file {file_path}: {e}")

    return dialogs


def get_dialog_scope(
    branch: str = "main",
    bin_dir: str = "bin",
    repo_url: str = RBHR_MAIA_GITHUB_REPO_URL,
) -> List[Dialog]:
    requirements_path = refresh(repo_url, branch, bin_dir)
    dialogs_dir = os.path.join(requirements_path, "bots/default/dialog_requirements/dialogs")

    if not os.path.exists(dialogs_dir):
        raise RuntimeError(f"Dialog requirements directory does not exist: {dialogs_dir}")

    return load_dialogs_from_dir(dialogs_dir)
