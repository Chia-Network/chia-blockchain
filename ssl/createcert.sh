#!/bin/bash
echo "First arg: $1"
openssl genrsa -aes256 -passout pass:1234 -aes256 -out $1.key 4096
openssl req -passin pass:1234 -new -nodes -key $1.key -out $1.csr -subj "/CN=$1"
openssl x509 -days 6000 -passin pass:1234 -req -in $1.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out $1.crt

