import datetime
import os
import pickle
import subprocess

import requests
import yaml


def fetch_file(filepath: str, branch: str = "master") -> requests.Response:
    url = f"https://raw.code.rbi.tech/raiffeisen/maia-bot-rbhr-raia/{branch}/{filepath}"
    token = os.getenv("GITHUB_PAT")

    if not token:
        raise RuntimeError(
            "GitHub Personal Access Token (GITHUB_PAT) is not set in the environment variables."
        )

    headers = {"Authorization": f"token {token}"}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to fetch file from {url}") from e


def fetch_file_text(filepath: str, branch: str = "master") -> str:
    try:
        return fetch_file(filepath, branch).text
    except ValueError:
        raise ValueError("The response content is not valid text data.")


def get_files_and_dirs(dir_path: str, branch: str = "main") -> dict[str, list[str]]:
    url = (
        "https://api.code.rbi.tech/repos/raiffeisen/maia-bot-rbhr-raia/contents/"
        f"{dir_path}?ref={branch}"
    )
    token = os.getenv("GITHUB_PAT")

    if not token:
        raise RuntimeError(
            "GitHub Personal Access Token (GITHUB_PAT) is not set in the environment variables."
        )

    headers = {"Authorization": f"token {token}"}

    try:
        categorized_data = {"files": [], "dirs": []}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        for item in response.json():
            if item["type"] == "file":
                categorized_data["files"].append(item["path"])
            elif item["type"] == "dir":
                categorized_data["dirs"].append(item["path"])
        return categorized_data
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to fetch file from {url}") from e


def get_dialog_requirements(branch: str = "master") -> list:
    dialogs = []

    try:
        dirs = get_files_and_dirs(
            "bots/default/dialog_requirements/dialogs", branch=branch
        )["dirs"]
    except Exception as e:
        print(f"Error fetching directories: {e}")
        return dialogs

    for dir_path in dirs:
        try:
            files = get_files_and_dirs(dir_path, branch=branch)["files"]
        except Exception as e:
            print(f"Error fetching files in directory {dir_path}: {e}")
            continue

        for file in files:
            try:
                parsed_data = yaml.safe_load(fetch_file(file, branch=branch).text)
                second_key = next(iter(parsed_data["dialogs"]))
                dialogs.append(parsed_data["dialogs"][second_key])
            except yaml.YAMLError as e:
                print(f"Error parsing YAML file {file}: {e}")
            except Exception as e:
                print(f"Error fetching file {file}: {e}")

    return dialogs


def get_dialog_requirements_map(branch: str = "master") -> dict:
    dialogs = get_dialog_requirements(branch=branch)
    dialogs_map: dict = {}

    for dialog in dialogs:
        dialogs_map.setdefault(dialog["name"], dialog)

    return dialogs_map


def write_dialog_requirements_binary(out_dir: str, branch: str = "master") -> None:
    dialogs = get_dialog_requirements(branch=branch)

    out_dir = out_dir[:-1] if out_dir.endswith("/") else out_dir
    fname = branch.replace("\\", "-").replace("/", "-")

    try:
        output_path = f"{out_dir}/dialog_requirements_{fname}.pkl"
        with open(output_path, "wb") as file:
            pickle.dump(dialogs, file=file)
    except Exception as e:
        raise RuntimeError(f"Couldn't write the binary file: {e}")

    print(f"Dialogs for branch {branch} written in: {output_path}")


def read_dialog_requirements_binary(file_path: str) -> list:
    try:
        with open(file_path, "rb") as file:
            dialogs = pickle.load(file=file)
        return dialogs
    except Exception as e:
        raise RuntimeError(f"Couldn't load from binary: {e}")


def fetch_last_commits(count: int = 30, path: str = "/") -> requests.Response:
    url = (
        "https://api.code.rbi.tech/repos/raiffeisen/maia-bot-rbhr-raia/commits"
        f"?per_page={count}&path={path}"
    )
    token = os.getenv("GITHUB_PAT")

    if not token:
        raise RuntimeError(
            "GitHub Personal Access Token (GITHUB_PAT) is not set in the environment variables."
        )

    headers = {"Authorization": f"token {token}"}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to fetch file from {url}") from e


def get_live_dialog_requirements(binary_path: str, branch: str = "master"):
    if os.path.exists(binary_path):
        binary_last_mtime = os.path.getmtime(binary_path)
    else:
        binary_last_mtime = 0

    try:
        for commit in fetch_last_commits(
            count=10, path="bots/default/dialog_requirements/dialogs"
        ).json():
            commit_time = datetime.datetime.strptime(
                commit["commit"]["author"]["date"], "%Y-%m-%dT%H:%M:%SZ"
            ).timestamp()

            if commit_time > binary_last_mtime or not os.path.exists(binary_path):
                print("There was an update to dialogs, please wait...")
                write_dialog_requirements_binary(
                    "/".join(binary_path.split("/")[:-1]), branch=branch
                )
                print("Successfully updated dialog requirements binary")
                break

        return read_dialog_requirements_binary(binary_path)
    except Exception as e:
        raise RuntimeError("Failed parsing dialog requirements data") from e


def pull_repository(repo_url: str, branch: str = "main", bin_dir: str = "bin") -> str:
    repo_name = repo_url.split("/")[-1]
    branch_dir = os.path.join(bin_dir, repo_name, branch)

    if not os.path.exists(branch_dir):
        os.makedirs(branch_dir)

    try:
        subprocess.run(
            ["git", "clone", "--branch", branch, repo_url, branch_dir],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to clone repository: {e}")

    return branch_dir


def refresh(repo_url: str, branch: str = "master", bin_dir: str = "bin") -> str:
    repo_name = repo_url.split("/")[-1]
    branch_dir = os.path.join(bin_dir, repo_name, branch)

    if not os.path.exists(branch_dir):
        return pull_repository(repo_url, branch, bin_dir)

    try:
        subprocess.run(["git", "-C", branch_dir, "pull", "origin", branch], check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to pull changes for repository: {e}")

    return branch_dir
