#!/usr/bin/env bash

set -o errexit

USAGE_TEXT="\\
Usage: $0 <bladebit|madmax> [-v VERSION | -h]

  -v VERSION    Specify the version of plotter to install
  -h            Show usage
"

usage() {
  echo "$USAGE_TEXT"
}

# Check for necessary tools
if ! command -v wget &>/dev/null; then
  echo "ERROR: wget could not be found. Please install wget and try again."
  exit 1
fi

if ! command -v tar &>/dev/null; then
  echo "ERROR: tar could not be found. Please install tar and try again."
  exit 1
fi

# Function to download, extract, set permissions, and clean up
handle_binary() {
  URL="$1"
  ARTIFACT=$(basename "$URL")
  FILENAME="$2"
  BINARY_NAME="$3"

  echo "Fetching binary from: ${URL}"
  if wget -q "$URL"; then
    echo "Successfully downloaded: ${ARTIFACT}"
    if [[ "$FILENAME" == *.tar.gz ]]; then
      tar zxf "$FILENAME"
      rm -f "$FILENAME"
    else
      mv "$ARTIFACT" "$BINARY_NAME"
    fi
    chmod 755 ./"$BINARY_NAME"
    echo -e "\nSuccessfully installed '${BINARY_NAME}' to:\n$PWD/${BINARY_NAME}\n"
  else
    echo -e "\nWARNING: Failed to download from ${URL}. Maybe specified version of the binary does not exist.\n"
  fi
}

get_bladebit_filename() {
  BLADEBIT_VER="$1" # e.g. v2.0.0-beta1
  OS="$2"           # "ubuntu", "centos", "macos"
  ARCH="$3"         # "x86-64", "arm64"

  echo "bladebit-${BLADEBIT_VER}-${OS}-${ARCH}.tar.gz"
}

get_bladebit_cuda_filename() {
  BLADEBIT_VER="$1" # e.g. v2.0.0-beta1
  OS="$2"           # "ubuntu", "centos", "macos"
  ARCH="$3"         # "x86-64", "arm64"

  echo "bladebit-cuda-${BLADEBIT_VER}-${OS}-${ARCH}.tar.gz"
}

get_bladebit_url() {
  BLADEBIT_VER="$1" # e.g. v2.0.0-beta1
  OS="$2"           # "ubuntu", "centos", "macos"
  ARCH="$3"         # "x86-64", "arm64"

  GITHUB_BASE_URL="https://github.com/Chia-Network/bladebit/releases/download"
  BLADEBIT_FILENAME="$(get_bladebit_filename "$BLADEBIT_VER" "$OS" "$ARCH")"

  echo "${GITHUB_BASE_URL}/${BLADEBIT_VER}/${BLADEBIT_FILENAME}"
}

get_bladebit_cuda_url() {
  BLADEBIT_VER="$1" # e.g. v2.0.0-beta1
  OS="$2"           # "ubuntu", "centos", "macos"
  ARCH="$3"         # "x86-64", "arm64"

  GITHUB_BASE_URL="https://github.com/Chia-Network/bladebit/releases/download"
  BLADEBIT_CUDA_FILENAME="$(get_bladebit_cuda_filename "$BLADEBIT_VER" "$OS" "$ARCH")"

  echo "${GITHUB_BASE_URL}/${BLADEBIT_VER}/${BLADEBIT_CUDA_FILENAME}"
}

get_madmax_filename() {
  KSIZE="$1"
  MADMAX_VER="$2"
  OS="$3"
  ARCH="$4"

  export CHIA_PLOT="chia_plot"
  if [ "$KSIZE" = "k34" ]; then
    export CHIA_PLOT="chia_plot_k34"
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
    SUFFIX="$ARCH"
  fi

  echo "${CHIA_PLOT}-${MADMAX_VER}-${SUFFIX}"
}

get_madmax_url() {
  KSIZE="$1"
  MADMAX_VER="$2"
  OS="$3"
  ARCH="$4"

  GITHUB_BASE_URL="https://github.com/Chia-Network/chia-plotter-madmax/releases/download"
  MADMAX_FILENAME="$(get_madmax_filename "$KSIZE" "$MADMAX_VER" "$OS" "$ARCH")"

  echo "${GITHUB_BASE_URL}/${MADMAX_VER}/${MADMAX_FILENAME}"
}

if [ "$1" = "-h" ] || [ "$1" = "" ]; then
  usage
  exit 0
fi

DEFAULT_BLADEBIT_VERSION="v3.1.0"
DEFAULT_BLADEBIT_VERSION_FOR_MACOS="v2.0.1"
DEFAULT_MADMAX_VERSION="0.0.2"
VERSION=
PLOTTER=$1
shift 1

while getopts v:h flag; do
  case "$flag" in
  v) VERSION="$OPTARG" ;;
  h)
    usage
    exit 0
    ;;
  *)
    echo
    usage
    exit 1
    ;;
  esac
done

SCRIPT_DIR=$(
  cd -- "$(dirname -- "$0")"
  pwd
)

if [ "$SCRIPT_DIR" != "$PWD" ]; then
  echo "ERROR: Please change working directory by the command below"
  echo "  cd ${SCRIPT_DIR}"
  exit 1
fi

if [ "$VIRTUAL_ENV" = "" ]; then
  echo "This requires the chia python virtual environment."
  echo "Execute '. ./activate' before running."
  exit 1
fi

if [ "$(id -u)" = 0 ]; then
  echo "WARN: Plotter should not be installed or run by the root user."
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
  elif [ -f /etc/os-release ]; then
    OS=$(grep -oP '(?<=^ID=).+' /etc/os-release | tr -d '"')
    if [ "$OS" == "arch" ]; then
      OS="ubuntu"
    fi
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

# Handle BladeBit and BladeBit CUDA binaries
if [ "$PLOTTER" = "bladebit" ]; then
  if [ "$VERSION" = "" ]; then
    if [ "$OS" = "macos" ]; then
      VERSION="$DEFAULT_BLADEBIT_VERSION_FOR_MACOS"
    else
      VERSION="$DEFAULT_BLADEBIT_VERSION"
    fi
  fi

  echo -e "Installing bladebit $VERSION\n"

  # Regular bladebit binary
  url="$(get_bladebit_url "$VERSION" "$OS" "$ARCH")"
  bladebit_filename="$(get_bladebit_filename "$VERSION" "$OS" "$ARCH")"
  handle_binary "$url" "$bladebit_filename" "bladebit"

  # CUDA bladebit binary
  if [ "$OS" != "macos" ]; then
    url="$(get_bladebit_cuda_url "$VERSION" "$OS" "$ARCH")"
    bladebit_cuda_filename="$(get_bladebit_cuda_filename "$VERSION" "$OS" "$ARCH")"
    handle_binary "$url" "$bladebit_cuda_filename" "bladebit_cuda"
  fi

# Handle MadMax binaries
elif [ "$PLOTTER" = "madmax" ]; then
  if [ "$VERSION" = "" ]; then
    VERSION="$DEFAULT_MADMAX_VERSION"
  fi

  echo -e "Installing madmax $VERSION\n"

  # k32 MadMax binary
  url="$(get_madmax_url "k32" "$VERSION" "$OS" "$ARCH")"
  madmax_filename="$(get_madmax_filename "k32" "$VERSION" "$OS" "$ARCH")"
  handle_binary "$url" "$madmax_filename" "chia_plot"
  # k34 MadMax binary
  url="$(get_madmax_url "k34" "$VERSION" "$OS" "$ARCH")"
  madmax_filename="$(get_madmax_filename "k34" "$VERSION" "$OS" "$ARCH")"
  handle_binary "$url" "$madmax_filename" "chia_plot_k34"
else
  usage
fi
