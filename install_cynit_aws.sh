#!/usr/bin/env bash
set -euo pipefail

BUCKET_PATH="s3://mijn-bucket/cynit/cynit_bundle_latest.zip"
INSTALL_ROOT="/opt/cynit"
ZIP_PATH="/tmp/cynit_bundle_latest.zip"

echo "Download bundle from ${BUCKET_PATH}..."
aws s3 cp "${BUCKET_PATH}" "${ZIP_PATH}"

sudo mkdir -p "${INSTALL_ROOT}"
sudo unzip -o "${ZIP_PATH}" -d "${INSTALL_ROOT}"

cd "${INSTALL_ROOT}"

# Zoek bundle dir
BUNDLE_DIR=$(ls -d cynit_bundle_* | sort | tail -n 1)
if [ -z "$BUNDLE_DIR" ]; then
  echo "No cynit_bundle_* found in ${INSTALL_ROOT}"
  exit 1
fi

CYNIT_DIR="${INSTALL_ROOT}/${BUNDLE_DIR}/CyNiT-tools"
SPYT_DIR="${INSTALL_ROOT}/${BUNDLE_DIR}/SP-YT"

# Venv voor CyNiT
cd "${CYNIT_DIR}"
python3 -m venv venv
source venv/bin/activate
if [ -f "${INSTALL_ROOT}/${BUNDLE_DIR}/requirements_cynit.txt" ]; then
  pip install -r "${INSTALL_ROOT}/${BUNDLE_DIR}/requirements_cynit.txt"
fi
deactivate

# Venv voor SP-YT
cd "${SPYT_DIR}"
python3 -m venv venv
source venv/bin/activate
if [ -f "${INSTALL_ROOT}/${BUNDLE_DIR}/requirements_spyt.txt" ]; then
  pip install -r "${INSTALL_ROOT}/${BUNDLE_DIR}/requirements_spyt.txt"
fi
deactivate

echo "CyNiT installed under ${INSTALL_ROOT}"
