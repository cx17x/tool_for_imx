import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from shlex import quote


# ====== EDIT THESE SETTINGS ======
SOURCE_HOST = "ubc-one-spb-server"
SOURCE_PORT = None
SOURCE_KEY_FILE = None
SOURCE_REMOTE_FOLDER = "/home/ubc/naburov/ValiantTrain/train/drone_mix_20260317_201433/weights/int8_compare/q_imx_model"
# /home/ubc/naburov/ValiantTrain/quantization/imx_rpk/runs/run_20260325_225715/artifacts/q_imx_model/q_imx_model.rpk

DEST_HOST = "192.168.0.129"
DEST_USER = "qwerty"
DEST_PORT = None
DEST_KEY_FILE = None
DEST_PASSWORD = "12345"
DEST_BASE_PATH = "/home/qwerty/"

LOCAL_WORKDIR = Path(__file__).resolve().parent / "_transfer_work"
DELETE_LOCAL_COPY_AFTER_SUCCESS = True
# ================================


def make_env_with_password(password):
    temp_file = tempfile.NamedTemporaryFile("w", delete=False)
    temp_file.write("#!/bin/sh\n")
    temp_file.write('echo "$SSH_PASSWORD"\n')
    temp_file.close()
    os.chmod(temp_file.name, 0o700)

    env = os.environ.copy()
    env["SSH_PASSWORD"] = password
    env["SSH_ASKPASS"] = temp_file.name
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["DISPLAY"] = "1"
    return env, temp_file.name


def run(command, password=None):
    print("$", " ".join(command))
    if not password:
        subprocess.run(command, check=True)
        return

    env, askpass_file = make_env_with_password(password)
    try:
        subprocess.run(command, check=True, env=env, stdin=subprocess.DEVNULL)
    finally:
        os.remove(askpass_file)


def scp_command(port, key_file):
    command = ["scp", "-r"]
    if port:
        command += ["-P", str(port)]
    if key_file:
        command += ["-i", key_file]
    return command

def ssh_command(port, key_file):
    command = ["ssh"]
    if port:
        command += ["-p", str(port)]
    if key_file:
        command += ["-i", key_file]
    return command


def main():
    folder_name = SOURCE_REMOTE_FOLDER.rstrip("/").split("/")[-1]
    if not folder_name:
        raise ValueError("SOURCE_REMOTE_FOLDER must point to a specific folder.")

    LOCAL_WORKDIR.mkdir(parents=True, exist_ok=True)
    local_folder = LOCAL_WORKDIR / folder_name

    if local_folder.exists():
        shutil.rmtree(local_folder)

    source = f"{SOURCE_HOST}:{SOURCE_REMOTE_FOLDER}"
    destination = f"{DEST_USER}@{DEST_HOST}"

    run(scp_command(SOURCE_PORT, SOURCE_KEY_FILE) + [source, str(LOCAL_WORKDIR)])
    run(
        ssh_command(DEST_PORT, DEST_KEY_FILE) + [destination, f"mkdir -p {quote(DEST_BASE_PATH)}"],
        password=DEST_PASSWORD,
    )
    run(
        scp_command(DEST_PORT, DEST_KEY_FILE) + [str(local_folder), f"{destination}:{DEST_BASE_PATH}"],
        password=DEST_PASSWORD,
    )

    if DELETE_LOCAL_COPY_AFTER_SUCCESS:
        shutil.rmtree(local_folder)


if __name__ == "__main__":
    main()
