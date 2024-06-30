import os
import re
import requests
import subprocess
import yaml


def print_message(message: str, error: bool=False):
    """Print message to `stdout`. If `error` is `True`, then instantly exit the script with exit code 1.
    """
    if error:
        print(f"[ERROR] {message}")
        exit(1)
    print(f"[INFO] {message}")


def run_command(command: str) -> (bool, str):
    """Run shell command

    Args:
        command         : Command to run

    Returns:
        status, output  : Execution status (`True` if command exists with code 0) and the output (from `stdout` or `stderr`)
    """
    result = subprocess.run(command.split(" "), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    status = result.returncode == 0
    return status, result.stdout.decode("UTF-8") if status else result.stderr.decode("UTF-8")


def substitute_environment_variable(string: str) -> str:
    """Substitute the presence of substring with format `${...}` with the value from environment variable

    Args:
        original_string     : The original string 

    Returns:
        substituted_string  : The string after substituting the environment variable
    """
    pattern = re.compile(r"\${([^{]*)}")
    for match in pattern.finditer(string):
        env_value = os.environ[match.group(1)]
        string = string.replace(match.group(0), env_value)
    return string


class InstallConfig:
    """This class contains the configuration to install a package. A package can be installed from either a repository or
    from a remote RPM file. Package installation will only be done if the command defined in 'if_fail' exits with exit code 1.
    """
    def __init__(self, data: dict):
        self.if_fail: str                   = data["if_fail"]
        self.repo: str                      = data.get("repo")
        self.install_from_repo: str         = data.get("install_from_repo")
        self.install_from_remote_file: str  = data.get("install_from_remote_file")

        # Verification
        # Currently "if" does not support multiline command
        if "\n" in self.if_fail:
            print_message("'if_fail' does not support multiline command.", error=True)
        # Either 'install_from_repo' OR 'install_from_remote_file' must be defined
        if (not self.install_from_repo) == (not self.install_from_remote_file):
            print_message("Either 'install_from_repo' or 'install_from_remote_file' must be defined.", error=True)
        # If it installs from remote file, make the sure the URL is a download URL for an RPM file
        if self.install_from_remote_file and not self.install_from_remote_file.endswith(".rpm"):
            print_message("Remote file must be an RPM file.", error=True)


    def should_be_installed(self) -> bool:
        """Check whether the package should be installed or not

        Returns:
            should_be_installed: `True` if package should be installed, otherwise `False`
        """
        status, _ = run_command(self.if_fail)
        return not status


    def install(self):
        """Install the package
        """
        if self.should_be_installed():
            if self.install_from_repo:
                self.__install_from_repo()
            elif self.__install_from_remote_file:
                self.__install_from_remote_file()


    def __install_from_repo(self):
        """Install the package from repository. If 'repo' is defined, then add the repo first, before installing it.
        """
        if self.repo:
            print_message(f"Adding repo {self.repo}")
            command = f"sudo dnf config-manager -y --add-repo {self.repo}"
            status, _ = run_command(command)
            if not status:
                print_message(f"Failed to add repo {self.repo}: {output}", error=True)

        print_message(f"Installing package {self.install_from_repo}")
        command = f"sudo dnf install -y {self.install_from_repo}"
        status, output = run_command(command)
        if not status:
            print_message(f"Failed to install package: {output}", error=True)


    def __install_from_remote_file(self):
        """Install the package from RPM remote file. The file will be downloaded first and stored temporarily in `/tmp`.
        """
        print_message(f"Downloading remote file {self.install_from_remote_file}")
        res = requests.get(self.install_from_remote_file)
        if res.status_code != 200:
            print_message(f"Failed to download remote file from {self.install_from_remote_file}: {res.text}", error=True)
        filename = self.install_from_remote_file.split("/")[-1]
        filename = f"/tmp/{filename}"
        with open(filename, "wb") as file:
            file.write(res.content)

        print_message(f"Installing package from file {filename}")
        command = f"sudo dnf install -y {filename}"
        status, output = run_command(command)
        if not status:
            print_message(f"Failed to install package: {output}", error=True)


class FilesConfig:
    """This class contains configuration to manage files.
    """
    ACTION_CREATED  = 1
    ACTION_UPDATED  = 2
    ACTION_NONE     = 3


    def __init__(self, data: dict):
        self.files = []
        for origin_file, target_file in data.items():
            action = FilesConfig.ACTION_NONE
            target_file = substitute_environment_variable(target_file)
            if not os.path.exists(target_file):
                action = FilesConfig.ACTION_CREATED
            else:
                if open(origin_file, "r").read() != open(target_file, "r").read():
                    action = FilesConfig.ACTION_UPDATED

            self.files.append({
                "origin_file": origin_file,
                "origin_file_content": open(origin_file, "r").read(),
                "target_file": target_file,
                "action": action
            })


    def write_files(self):
        """Create or update files
        """
        for each in self.files:
            action = each["action"]
            if action == FilesConfig.ACTION_CREATED:
                print_message(f"Creating file {each['target_file']}")
                try:
                    os.makedirs(os.path.dirname(each["target_file"]), exist_ok=True)
                    with open(each["target_file"], "w") as file:
                        file.write(each["origin_file_content"])
                except PermissionError:
                    command = f"sudo mkdir -p {os.path.dirname(each['target_file'])}"
                    _, _ = run_command(command)
                    command = f"sudo cp {each['origin_file']} {each['target_file']}"
                    _, _ = run_command(command)
            elif action == FilesConfig.ACTION_UPDATED:
                print_message(f"Updating file {each['target_file']}")
                try:
                    with open(each["target_file"], "w") as file:
                        file.write(each["origin_file_content"])
                except PermissionError:
                    command = f"sudo cp {each['origin_file']} {each['target_file']}"
                    _, _ = run_command(command)


class Entry:
    """This class represent a single entry from a configuration file.
    """
    def __init__(self, name: str, data: dict):
        install_config                      = data.get("install")
        files_config                        = data.get("files")

        self.name: str                      = name
        self.install_config: InstallConfig  = InstallConfig(install_config) if install_config else None
        self.files_config: FilesConfig      = FilesConfig(files_config) if files_config else None


    def get_actions(self):
        actions = []
        if self.install_config and self.install_config.should_be_installed():
            package = self.install_config.install_from_repo if self.install_config.install_from_repo else self.install_config.install_from_remote_file
            actions.append(f"Package will be installed: {package}")
        if self.files_config:
            for each in self.files_config.files:
                action = each["action"]
                target_file = each["target_file"]
                if action == FilesConfig.ACTION_CREATED:
                    actions.append(f"File will be created: {target_file}")
                elif action == FilesConfig.ACTION_UPDATED:
                    actions.append(f"File will be updated: {target_file}")

        print(f"Name: {self.name}")
        if actions:
            for each in actions:
                print(each)
        else:
            print("OK")
        print()
        return actions != []


if __name__ == "__main__":
    # Get entries from config
    entries = []
    for name, data in yaml.load(open("config.yaml", "r").read(), Loader=yaml.FullLoader).items():
        entries.append(Entry(name, data))

    any_actions = False
    for each in entries:
        any_actions = each.get_actions() or any_actions
    if any_actions and input("Are you sure to continue? Type 'Y' to continue: ") == "Y":
        for each in entries:
            if each.install_config:
                each.install_config.install()
            if each.files_config:
                each.files_config.write_files()
