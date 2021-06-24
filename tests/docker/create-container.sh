#!/bin/sh

MINICONDA=Miniconda3-py39_4.9.2-Linux-x86_64.sh
wget "https://repo.anaconda.com/miniconda/${MINICONDA}"
MINICONDA_VERIFY=536817d1b14cb1ada88900f5be51ce0a5e042bae178b5550e62f61e223deae7c
MINICONDA_HASH=$(shasum -a 256 "${MINICONDA}" | awk '{print $1}')

if [ "${MINICONDA_HASH}" != "${MINICONDA_VERIFY}" ] ; then
    echo 'Bad conda download (wrong hash)'
    exit 1
fi

sh "${MINICONDA}" -b -p "/home/chia/miniconda"
CONDA="/home/chia/miniconda/bin/conda"
"${CONDA}" init

while read PYVER ; do
    echo python "$PYVER"
    "${CONDA}" update -n base -c defaults conda
    "${CONDA}" env create -f "environment$PYVER.yml"
    "${CONDA}" run -n "python$PYVER" sh run-in-container.sh "${PYVER}"
done < /app/pyvers.txt
