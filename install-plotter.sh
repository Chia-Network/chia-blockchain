#!/bin/bash

set -o errexit

USAGE_TEXT="\
Usage: $0 <bladebit|madmax> [-v VERSION | -h]

  -v VERSION    Specify the version of plotter to install
  -h            Show usage
"

usage() {
  echo "${USAGE_TEXT}"
}

get_bladebit_filename() {
  BLADEBIT_VER="$1" # e.g. v2.0.0-beta1
  OS="$2" # "ubuntu", "centos", "macos"
  ARCH="$3" # "x86-64", "arm64"

  echo "bladebit-${BLADEBIT_VER}-${OS}-${ARCH}.tar.gz"
}

get_bladebit_url() {
  BLADEBIT_VER="$1" # e.g. v2.0.0-beta1
  OS="$2" # "ubuntu", "centos", "macos"
  ARCH="$3" # "x86-64", "arm64"

  GITHUB_BASE_URL="https://github.com/Chia-Network/bladebit/releases/download"
  BLADEBIT_FILENAME="$(get_bladebit_filename "${BLADEBIT_VER}" "${OS}" "${ARCH}")"

  echo "${GITHUB_BASE_URL}/${BLADEBIT_VER}/${BLADEBIT_FILENAME}"
}

get_madmax_filename() {
  KSIZE="$1" # "k34" or other
  MADMAX_VER="$2" # e.g. 0.0.2
  OS="$3" # "macos", others
  ARCH="$4" # "arm64", "x86-64"

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
  KSIZE="$1" # "k34" or other
  MADMAX_VER="$2" # e.g. 0.0.2
  OS="$3" # "macos", others
  ARCH="$4" # "intel", "m1", "arm64", "x86-64"

  GITHUB_BASE_URL="https://github.com/Chia-Network/chia-plotter-madmax/releases/download"
  MADMAX_FILENAME="$(get_madmax_filename "${KSIZE}" "${MADMAX_VER}" "${OS}" "${ARCH}")"

  echo "${GITHUB_BASE_URL}/${MADMAX_VER}/${MADMAX_FILENAME}"
}


if [ "$1" = "-h" ] || [ -z "$1" ]; then
  usage
  exit 0
fi

DEFAULT_BLADEBIT_VERSION="v2.0.0"
DEFAULT_MADMAX_VERSION="0.0.2"
VERSION=
PLOTTER=$1
shift 1

while getopts v:h flag
do
  case "${flag}" in
    # version
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
  # Debian / Ubuntu
  if command -v apt-get >/dev/null; then
    echo "Detected Debian/Ubuntu like OS"
    OS="ubuntu"
  # RedHut / CentOS / Rocky / AMLinux
  elif type yum >/dev/null 2>&1; then
    echo "Detected RedHut like OS"
    OS="centos"
  else
    echo "ERROR: Unknown Linux distro"
    exit 1
  fi
# MacOS
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
  if ! wget -q "${URL}"; then
    echo "ERROR: Download failed. Maybe specified version of the binary does not exist."
    exit 1
  fi
  echo "Successfully downloaded: ${URL}"
  bladebit_filename="$(get_bladebit_filename "${VERSION}" "${OS}" "${ARCH}")"
  tar zxf "${bladebit_filename}"
  chmod 755 ./bladebit
  rm -f "${bladebit_filename}"
  echo "Successfully installed bladebit to $(pwd)/bladebit"
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
