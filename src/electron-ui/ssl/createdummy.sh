#!/bin/bash
echo "First arg: $1"
openssl genrsa -aes256 -passout pass:1234 -aes256 -out $1.key 1024
openssl req -x509 -days 6000 -passin pass:1234 -new -nodes -key $1.key -out $1.crt -subj "/CN=Dummy SSL Auth Cert"
