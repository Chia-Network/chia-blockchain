#!/bin/bash

set -o errexit

USAGE_TEXT="\\
Usage: $0 <bladebit|madmax> [-v VERSION | -h]

  -v VERSION    Specify the version of plotter to install
  -h            Show usage
"

usage() {
  echo "${USAGE_TEXT}"
}

get_bladebit_filename() {
  BLADEBIT_VER="$1"
  OS="$2"
  ARCH="$3"

  echo "bladebit-${BLADEBIT_VER}-${OS}-${ARCH}.tar.gz"
}

get_bladebit_cuda_filename() {
  BLADEBIT_VER="$1"
  OS="$2"
  ARCH="$3"

  echo "bladebit-cuda-${BLADEBIT_VER}-${OS}-${ARCH}.tar.gz"
}

get_bladebit_url() {
  BLADEBIT_VER="$1"
  OS="$2"
  ARCH="$3"

  GITHUB_BASE_URL="https://github.com/Chia-Network/bladebit/releases/download"
  BLADEBIT_FILENAME="$(get_bladebit_filename "${BLADEBIT_VER}" "${OS}" "${ARCH}")"

  echo "${GITHUB_BASE_URL}/${BLADEBIT_VER}/${BLADEBIT_FILENAME}"
}

get_bladebit_cuda_url() {
  BLADEBIT_VER="$1"
  OS="$2"
  ARCH="$3"

  GITHUB_BASE_URL="https://github.com/Chia-Network/bladebit/releases/download"
  BLADEBIT_CUDA_FILENAME="$(get_bladebit_cuda_filename "${BLADEBIT_VER}" "${OS}" "${ARCH}")"

  echo "${GITHUB_BASE_URL}/${BLADEBIT_VER}/${BLADEBIT_CUDA_FILENAME}"
}

get_madmax_filename() {
  KSIZE="$1"
  MADMAX_VER="$2"
  OS="$3"
  ARCH="$4"

  CHIA_PLOT="chia_plot"
  if [ "$KSIZE" = "k34" ]; then
    CHIA_PLOT="chia_plot_k34"
  fi
  SUFFIX=""
  if [ "$OS" = "macos" ]; then
    if [ "$ARCH" = "arm64" ]; then
      ARCH="m1"
    else
      ARCH="intel"
    fi
    SUFFIX="${OS}-${ARCH}"
  else
    SUFFIX="${ARCH}"
  fi

  echo "${CHIA_PLOT}-${MADMAX_VER}-${SUFFIX}"
}

get_madmax_url() {
  KSIZE="$1"
  MADMAX_VER="$2"
  OS="$3"
  ARCH="$4"

  GITHUB_BASE_URL="https://github.com/Chia-Network/chia-plotter-madmax/releases/download"
  MADMAX_FILENAME="$(get_madmax_filename "${KSIZE}" "${MADMAX_VER}" "${OS}" "${ARCH}")"

  echo "${GITHUB_BASE_URL}/${MADMAX_VER}/${MADMAX_FILENAME}"
}

if [ "$1" = "-h" ] || [ -z "$1" ]; then
  usage
  exit 0
fi

DEFAULT_BLADEBIT_VERSION="v2.0.1"
DEFAULT_MADMAX_VERSION="0.0.2"
VERSION=
PLOTTER=$1
shift 1

while getopts v:h flag
do
  case "${flag}" in
    v) VERSION="$OPTARG";;
    h) usage; exit 0;;
    *) echo; usage; exit 1;;
  esac
done

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")"; pwd)

if [ "${SCRIPT_DIR}" != "$(pwd)" ]; then
  echo "ERROR: Please change working directory by the command below"
  echo "  cd ${SCRIPT_DIR}"
  exit 1
fi

if [ -z "$VIRTUAL_ENV" ]; then
  echo "This requires the chia python virtual environment."
  echo "Execute '. ./activate' before running."
  exit 1
fi

if [ "$(id -u)" = 0 ]; then
  echo "ERROR: Plotter can not be installed or run by the root user."
  exit 1
fi

OS=""
ARCH="x86-64"
if [ "$(uname)" = "Linux" ]; then
  if command -v apt-get >/dev/null; then
    echo "Detected Debian/Ubuntu like OS"
    OS="ubuntu"
  elif type yum >/dev/null 2>&1; then
    echo "Detected RedHut like OS"
    OS="centos"
  else
    echo "ERROR: Unknown Linux distro"
    exit 1
  fi
elif [ "$(uname)" = "Darwin" ]; then
  echo "Detected MacOS"
  OS="macos"
else
  echo "ERROR: $(uname) is not supported"
  exit 1
fi

if [ "$(uname -m)" = "aarch64" ] || [ "$(uname -m)" = "arm64" ]; then
  ARCH="arm64"
fi

if [ ! -d "${VIRTUAL_ENV}/bin" ]; then
  echo "ERROR: venv directory does not exists: '${VIRTUAL_ENV}/bin'"
  exit 1
fi
cd "${VIRTUAL_ENV}/bin"

if [ "$PLOTTER" = "bladebit" ]; then
  if [ -z "$VERSION" ]; then
    VERSION="$DEFAULT_BLADEBIT_VERSION"
  fi

  echo "Installing bladebit $VERSION"

  URL="$(get_bladebit_url "${VERSION}" "${OS}" "${ARCH}")"
  echo "Fetching binary from: ${URL}"
  if wget -q "${URL}"; then
    echo "Successfully downloaded: ${URL}"
    bladebit_filename="$(get_bladebit_filename "${VERSION}" "${OS}" "${ARCH}")"
    tar zxf "${bladebit_filename}"
    chmod 755 ./bladebit
    rm -f "${bladebit_filename}"
    echo "Successfully installed bladebit to $(pwd)/bladebit"
  else
    echo "WARNING: Could not download BladeBit. Maybe specified version of the binary does not exist."
  fi

  URL="$(get_bladebit_cuda_url "${VERSION}" "${OS}" "${ARCH}")"
  echo "Fetching CUDA binary from: ${URL}"
  if wget -q "${URL}"; then
    echo "Successfully downloaded CUDA: ${URL}"
    bladebit_cuda_filename="$(get_bladebit_cuda_filename "${VERSION}" "${OS}" "${ARCH}")"
    tar zxf "${bladebit_cuda_filename}"
    chmod 755 ./bladebit_cuda
    rm -f "${bladebit_cuda_filename}"
    echo "Successfully installed bladebit_cuda to $(pwd)/bladebit_cuda"
  else
    echo "WARNING: Could not download BladeBit CUDA. Maybe specified version of the CUDA binary does not exist."
  fi
elif [ "$PLOTTER" = "madmax" ]; then
  if [ -z "$VERSION" ]; then
    VERSION="$DEFAULT_MADMAX_VERSION"
  fi

  echo "Installing madmax $VERSION"

  URL="$(get_madmax_url k32 "${VERSION}" "${OS}" "${ARCH}")"
  echo "Fetching binary from: ${URL}"
  if ! wget -q "${URL}"; then
    echo "ERROR: Download failed. Maybe specified version of the binary does not exist."
    exit 1
  fi
  echo "Successfully downloaded: ${URL}"
  madmax_filename="$(get_madmax_filename "k32" "${VERSION}" "${OS}" "${ARCH}")"
  mv -f "${madmax_filename}" chia_plot
  chmod 755 chia_plot
  echo "Successfully installed madmax to $(pwd)/chia_plot"

  URL="$(get_madmax_url k34 "${VERSION}" "${OS}" "${ARCH}")"
  echo "Fetching binary from: ${URL}"
  if ! wget -q "${URL}"; then
    echo "madmax for k34 for this version is not found"
    exit 1
  fi
  echo "Successfully downloaded: ${URL}"
  madmax_filename="$(get_madmax_filename "k34" "${VERSION}" "${OS}" "${ARCH}")"
  mv -f "${madmax_filename}" chia_plot_k34
  chmod 755 chia_plot_k34
  echo "Successfully installed madmax for k34 to $(pwd)/chia_plot_k34"
else
  usage
fi
