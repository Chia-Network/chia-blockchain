from __future__ import annotations

from typing import Dict, Tuple

SSL_TEST_PRIVATE_CA_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDKTCCAhGgAwIBAgIUXU/nGxb+rZck2qIMztmDWKDZCBcwDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMB4XDTIyMDMyMzE3MjkyNloXDTMyMDMy
MDE3MjkyNlowRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8G
A1UECwwYT3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMIIBIjANBgkqhkiG9w0BAQEF
AAOCAQ8AMIIBCgKCAQEAm8r7ngBPSkz0U2XxFwI0gT3xt/yqKTI0AZiSicyyMNo0
oSHZHRVzIfzu/c+cI2SPFHA0n9ZaswiztWje38uzRjEqD30EmF1By54A6c5pDJgV
MVd6LXafbv7tWxSLdyLPJkoa8gcqAtR1tOFXRHRtKNa6g2thyU87/V/UXJ9+C4eQ
mmpq3goVzkA7ZRx0FbdXwijAGLcL5ZWStUPTaWjR+V3ApxUZYy8JV3tWybEm5FDK
JJOvdd0bJQgT5WTCYRKNYsXyjcRP2ypi/Ry2M1oQLBbqCIldrvvIyoUodbkV3Yc7
AFhg4gUKc/O6zcIO/3PXKgFOAMLangjIBwWc9yyNXwIDAQABoxMwETAPBgNVHRMB
Af8EBTADAQH/MA0GCSqGSIb3DQEBCwUAA4IBAQCILSP1KclF/iLlNb7w2bE1hZ5/
IJcWsZJSec7vlZkF3AGxrUc2XzdT53gooZqpg5YIdMYqDZqCfPphvUbqGELbImfH
D7sWhD8jU0FsKc5ho6+Uwmj2I5H+xnSVSF8qEbSBk8nasAac+bXQ6cakqkG/cbO0
9HBBHTd6V25KCeyvYN0kyuYMyT7GBfzOBmhyx5zf2L3oqoqVKAokbmC/9cvBXMUX
+1BWyowMjBVH5C5frOymcTF7b3ZlMuibFdl01lVa76QjVno/QMZ2bqnLaqDJA306
f7vTyuGSYJSoXnEh0UJ4IR2ct0F+6JvuTCL4p/b97C4Au+Lq9jt+2sGV9CAs
-----END CERTIFICATE-----
"""

SSL_TEST_PRIVATE_CA_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCbyvueAE9KTPRT
ZfEXAjSBPfG3/KopMjQBmJKJzLIw2jShIdkdFXMh/O79z5wjZI8UcDSf1lqzCLO1
aN7fy7NGMSoPfQSYXUHLngDpzmkMmBUxV3otdp9u/u1bFIt3Is8mShryByoC1HW0
4VdEdG0o1rqDa2HJTzv9X9Rcn34Lh5CaamreChXOQDtlHHQVt1fCKMAYtwvllZK1
Q9NpaNH5XcCnFRljLwlXe1bJsSbkUMokk6913RslCBPlZMJhEo1ixfKNxE/bKmL9
HLYzWhAsFuoIiV2u+8jKhSh1uRXdhzsAWGDiBQpz87rNwg7/c9cqAU4AwtqeCMgH
BZz3LI1fAgMBAAECggEActMdtuuFhT7IyXsWQZ4XcrZkJPYtuGVPHWoFf1kGcKkz
JxvaeOwpSoCw6RMOgquIJUk6ECCeAtzED033Dr2FKZPs6zN6oo4Bg4C2LZ07odOp
sw9FdqK6icWMzZeL30gho5f02jPbi/BpvOJlPogNOI9jMp9/mC81CN+LlqTa8sVW
jABAfUx/d2HzqO+EP0+ku9iJQva1vfDnXhwuFRC2uT1gyE4yYIwofwfG9T/wiwaE
s07C46JDY7q1ct+V365233efQnKyHNE1zKUjbfUqVOHErcGJeS7amUT+rDsrexbT
VqZpVru2t9bGs6/tdAXy7g45ws7tbHU7UtiB9usCGQKBgQDOZmwJ5MxMYnE1uSP9
nLmtT/7DKfmwWXrF/NePrhfRGLoLwAo0EjujVPjNKnxpQYcCDVIBbk4ZYLm9WAAK
sh8hagWmDlHH2XUSTJlVzNfS1uMtptB4DuPiscasosrfwcW1/uXIdegZWPnme+XG
uL231fTZyUGrPZbMlESJphsXNQKBgQDBOz62H7KEkjAsiqpJ4rq0+Ar05+ngzdB/
wsPvI5kPyqZV1GXPwfZomFtyHIsadqPQklKUf3exTzXBngujdSjBvW6r6p3P+e5/
YzLrMXAbbz7DDooeeSyztca8ZCMssG0uKiWPzc+LmWQpyzKl/SmycpXxwpileigi
h3YzJT5gwwKBgHFaHotwdCKfDb2LaBCoOfDMtgVI0C/hdGO3cEsgOUREaCh71x6x
xL72s405gAnuSs79scPHaGzXiipKYft9x0r6hw+jXZZ7/qeGGc/dJ8pK6YjwzByj
UNP2/j1hSjmImaRR0LA+0LDbBKNn99EjNE352vagaMg6ks7Xvqw55TbhAoGATaTe
uBPYicisLtmxP2spltosnOgrZDePVicO0CK/uEa3u7lTB75qovDFnf62LnYJsR96
q0zk7Yxkj15QUuga7m6N7+qgaxeErA9SQItm/r8euwY2nbQXMEcUilK6h5SE6o3o
9fW/Ndr3Eowh1+z4Okos0i5dY/DH+8fuyPJoND0CgYBRp3/mQNwr8XBKSU16eohN
af1z84V5xvpnq74XtM+KuV5c9uE1DShdRbylVWcunNZZam71qbGVL/hri3v+VMTJ
hpPquyMmvlkG8OsgHAVzfO9dZjFtj2GcJE8tB9ElGG6s4lgQHIQOPKJdED1Y8dwi
GkpUY3wMbKPH+C8mN9NBHw==
-----END PRIVATE KEY-----
"""

SSL_TEST_FULLNODE_PRIVATE_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUPIoys/kxRUAxhIW+huwsgqplVZ0wDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyNloYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQCpDfVovOj9fLjpheYdKVwV5V3hN/bUxqlYAW3s+zFU9Bpg
+SnI+5XuTW6SLpiPjx/5kZJsztqxI/Nr7BuTpHUOfbaCHkoJGBAcAkPdnOma8lH7
bpZ8CpVjONeHqmTvsDP2dgCg8QW6nqVksEHMtkOFadTifIODxdWJtsB4KjzKlV1U
aiF0hUIJmbvX08bArrzrsX5EgM3pQV6vgo1wYWM/X9zRjAd0xJDbhVqOsQpK4AJS
zAAfqCwxNf04EHhRFD35Uam4NiBOzR3T8rB4XGcpMBYLPC6reLHtOmxneJ081NWh
ZgVDhxPg8/30Bs3OhNhT9ZlfBJZvPW8ReT/JzHXtAgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQA4hi9UEfJtPMsTjpI08Pdp
AMNa1ybci7kDVaMfcvKvMDcOtoCEt5K1t3fGWrYojfgnJnSRJLTSZIa7IdBbyZG7
e5ClNLzw6bCqiQ55mgyAFMFM0VUaYu39zRK5X6fA2qWXFYVbOGAbEgU8sFuOmBid
MjkEQKL561tiibAkVJucp0hLf1xzoH4dJZqFWyFiThH8RTUq4Gd4atH0pzk01Ts3
VbQyinIqEU/gwLAawnOGtdMYdFPNtll0F+lP1+h5AZYtsTcfilm18D9Th4/rfQay
Ob1SSSdL7MXqy0pR9sF/BiXTeXauOK6Y5DooJ32y68yrNKL+TfbEzcPSfqiaK3Tm
-----END CERTIFICATE-----
"""

SSL_TEST_FULLNODE_PRIVATE_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEvwIBADANBgkqhkiG9w0BAQEFAASCBKkwggSlAgEAAoIBAQCpDfVovOj9fLjp
heYdKVwV5V3hN/bUxqlYAW3s+zFU9Bpg+SnI+5XuTW6SLpiPjx/5kZJsztqxI/Nr
7BuTpHUOfbaCHkoJGBAcAkPdnOma8lH7bpZ8CpVjONeHqmTvsDP2dgCg8QW6nqVk
sEHMtkOFadTifIODxdWJtsB4KjzKlV1UaiF0hUIJmbvX08bArrzrsX5EgM3pQV6v
go1wYWM/X9zRjAd0xJDbhVqOsQpK4AJSzAAfqCwxNf04EHhRFD35Uam4NiBOzR3T
8rB4XGcpMBYLPC6reLHtOmxneJ081NWhZgVDhxPg8/30Bs3OhNhT9ZlfBJZvPW8R
eT/JzHXtAgMBAAECggEAI/VoIeMs295PprxoegN2JuIm2eUBh7jKBIIpU6MKlztk
8QOOs8Vv2sR1pHps0PxsnLUuJB7Lvaob+PS72Oe+TlrHG149+Tk5E/wXW2go+GBa
t9SKBdBqfjR1A9JmreUY6G+pKpKZ2VwtagFjvZt3OUWNlq9NehX2mdhZkDXLwHs0
WdoZ9oEd9zWI0nz1zAtXZCEANphvu0oiihmeU/Ijif+4XTz5SYrMoSnC0OzEnGyx
r8nvVitBLbvivXfITJgoaGyhUSFat8P53i0GUFYfAV9dAs9WBFDd27em8yoAwAw1
kRvSTbRZ4dxoDJtEZoQh7qW2o4YfabqPm5OTt9ivsQKBgQDV8TErf5WsooJVKSlG
mTLRtsuDBL5glTz2Q8G6t2lUEzFiH1e4Y3HE9gvq2soTmt9JcU/6zPxWqLtY4RcI
XMXHpkeIGiRpV1JYbUC+TXqUHfRS7nL+vZYGZ97NuuJsMz2hAtguVR3u0DEZT79I
hyJEQel96Wr56MuZ5Yod1Z1WkwKBgQDKScLYHzDg/BKgMwEHTEP0Uzqr/uJpcKGl
rifzKX9gtURmVKsLJYXPRrA8dBM6+zMTTF9QnXodgOS0xPe3IL1wN3lQc3z3OLvl
50Qw8uY+csPortA5VpVHdfo9SoDRIzWykzdRNdYXEWFhNRO250rqsxKx4MLEalj6
viE+ZH5RfwKBgQCU16/IvoPITmt0iiWAS3cytgUSiwtUMJ/wCSXQHGh4KL4zsPCb
hPwS9sdFxp/OUfJEq0PkjhaEx/FHnZojpD+pbgLYKq/oZesRQDlJ7Kd6QvjHdcOl
fQrSPBOjeACtHF0lFtCGM4uWqVtva679654odN7YTbuyUIbN9AdKSGKlZwKBgQCJ
RLRrY/8PLP6WpwWzphUW3sOZo0SQuFV40E1bvHUrctYPerT2w2eh2B4PZ9UE2SE3
n0OuuK39B1IrON2/7v+d/obcCQJr4JvgzqZ/cNS827QFWVsDDbYO4AgHP19ai8IM
g8mt2hKFZM3n4NSX8SvtR8cP3a1NC72FqS9130u4kQKBgQDUvc/QkoOiqSBIETCw
dvJJy/aqjbfEpmxOp1jT0LPSIbzAyRqNF1tCRaPXmSapiOGX+CmCZZ+cHjFGbMiE
qIj6TYC9WaJL221iB2o/Bgl1q6rg438fmEB1c/IuhviZhEXvopxh4l5XKNE9fC1u
iMlD8UUZlIqy47a2hq2Er68Ezg==
-----END PRIVATE KEY-----
"""

SSL_TEST_FULLNODE_PUBLIC_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUJ/ehUeJz6rFUOj2Sq6rL4SW0Wf0wDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyNloYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQCyjDKG7d7fU8ZdpnD0Ba5S3/F6FXpTvUBqxSRWOO9yI4tQ
hSqOJIP9x8u0aFhgmgMN8Rig3JZ6KfvCeQ1qO1xkcuZ1o3FoOOYkhZoj5OKjFQDk
6g+cOSrvUe4QtIaPxlfNhtV0peVQuKQGSOakEyC7Z5amZL7Ypwjbt6Wr/N5gZ2Be
2+UnoCOxYTVvUmOWl11Bre9eQZXYIM1D2oYht62HvGEMhoZD0NSoRsEiHPiJ5Hhi
ci+U/oO2XP9NrKK3LKr9A8NzWB6oHXqw7qidCQqGumY0zhE4MarACVzqJG6kCB4/
cL1I3eSjDT6iEUWwn1OLFc/sdTaB50LNfEI0DeL/AgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQCfYRU1NbezmtNTU1hvOHLn
Dcw1qrUujyl6XSE4kNPooKreJLQwtlV5EV1h9APIk11jrieiEkxo9IYVRzadyrrf
3Dh4x2KFn+R/m+ybHWTICcBL2FvvHuvVx/ilFraM3e+Kv/s+pQRs3YvQuCYduBTq
SXz12aZO5ttTmG7LK2WcX5OgwC1kmSw9Km2DFb8zu/cNv/VQkRujsG0doVVrqxHa
4/CkSlTBNCBJO2Brhtbpx4F6kKfK6u26i9pW6HHgvctpC5PORTeGofPVM26Hpsap
6mHfYpFu1jIr1MhQcWZss369DEwsSy2nr5/3R4zIDWMlBXEKd8p3ey/wjUk6dD+p
-----END CERTIFICATE-----
"""

SSL_TEST_FULLNODE_PUBLIC_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCyjDKG7d7fU8Zd
pnD0Ba5S3/F6FXpTvUBqxSRWOO9yI4tQhSqOJIP9x8u0aFhgmgMN8Rig3JZ6KfvC
eQ1qO1xkcuZ1o3FoOOYkhZoj5OKjFQDk6g+cOSrvUe4QtIaPxlfNhtV0peVQuKQG
SOakEyC7Z5amZL7Ypwjbt6Wr/N5gZ2Be2+UnoCOxYTVvUmOWl11Bre9eQZXYIM1D
2oYht62HvGEMhoZD0NSoRsEiHPiJ5Hhici+U/oO2XP9NrKK3LKr9A8NzWB6oHXqw
7qidCQqGumY0zhE4MarACVzqJG6kCB4/cL1I3eSjDT6iEUWwn1OLFc/sdTaB50LN
fEI0DeL/AgMBAAECggEADGHeqy7Z8wD7U8lUMggm08aGF6JfrmkEi6MKZxRhvreq
VLY3gk4T/Uia3vMRlfl4VsIupBFIOkapGA6PGJvvR2QUiXoBRmoTw9qkGvMnqImv
WzDETmBEkv5KlUv/vP7TXgSIzyMmKRf1AB6UKDLPZU/EydtYxOuomJw+2BOcVHEZ
H0pCdxUo7Kt9Y2bp7yvXSIx+G/HUchQkYQhXQAaxOl+NFzUBMNe+4on2IZC4C+EI
6t+fvlDuQrXLEqBigLwNeJ4hFGKsiGg5J0ae/UVYPuv0PbPsNarsBVCA8sC6He6X
ITfL6C8MxlwSliUe2vmH2pu+FKQHdQJ8lq8qZTwC6QKBgQDpulwHsVmr2NGEJVwM
4rYyIFR+zzchDzPf+OJhOytd+qtcNly+sIYnMxduoH8FoTpsDo1AwuDAiJeRMuPi
nKu0BGVpTlcFRvcpDbL7GRa8DafUhVImikR0YKWYi8NPe6xQi1wPNKve5rN9BKaN
UeSktbmBO1Qrx3AnfgRpdlyetQKBgQDDj8AIpP2Gq074mm9AOVPg0JdN8z9hW5B4
hRz3FlDCnuC4wReQYoRtOwJWMbMJWV4FH4mJuDmOBxKNV3o5pcQJduxS5+elAZQt
uucPz0qYlRyHkPJDBWSVfkhvMJrc4a+5qY1SjQQs+L2DFMmSkfa8WACgdIQ50H3j
bP8i5jlXYwKBgQCFeH+vgO6VPPbAgNklHp4u19mIpOp1fYoBH86e+bwVKd2LhhvG
ZWXmor2B1jNTUrPbGyA82Eyihh4Ps8EBGrjOzyfeT/dPsyvXjNQlojkiYKXzrcKw
8YqP7tUB3OZG0HghcsO6hziSzKm4/dvind501LW/f9LcQULhuovoccgIdQKBgHvD
igDuihSkbgIfmrDGlzL8UAVhIId472GWvNITKWFCM245pbQW5UBLzBrIsUoFaN9N
KjoigSpFh5Qz/IJnSj3DKaT+ZzeiXCjk1D7JLaiLFdcmAGwyCYoitazI0flgS1nw
2COaYz4i3a0LhtZf0gs4loz1sIj2TfWUkZOAqGGJAoGBAIk7JmrLFBcPTSPHEDMX
xvwQ+dy6WlYbSO9PjSNjGhHOvH/6gjUo7ZDpAW3IGMGJt/7AO5d80OOxqGhfwQHf
JBf6h8bh8In1Ybdo1yBHx6c996MqgLPBE1+j/okVwBWhWjuX6XBwUnivx3Upds/1
C3t2hlKCYatRJO8FMRbP6Pci
-----END PRIVATE KEY-----
"""

SSL_TEST_WALLET_PRIVATE_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUfnFEiDBphxztIz9efqOLOpYjA6YwDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyNloYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQDkLNTI9jghjYaXRMvt/3oFVDZ8FUraVUU718V8vW5NF4Or
I7HYi7EgS4BnRh9CfU8r+mkPxPTYJ7kgjKOcdNGw1ARCiIIl95gw6ymjcXZ7isLC
F+79kJNQSKq6lQvrPoKoQpfy8dgjRaGY7gH3DeX/Oi/QFd3N0C5ZGpyzE7+VmONg
gzoGk5MyLbBCcKcOsBQUqOR7p2bEYXDDP/xl7+u3R2rhWVsp/E9W0eJJmtiVwYrJ
y6sbzcWBxjCM3Rv4NZs9tTH19EHWDJM4whHgnEiB7eXz03+0tELhnwkrrm+a0qC2
uVqzG9HZ2/hVY0VmPyPVprAihsAPLyJlnpArCs4ZAgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQBUBe8jhAQgvnojPHIVbZTy
HyzRwfN8bx6sRGMzRWR1nFuSgeYz9ngzanf6adVCh7K7O8O1dZwdaPPZB9RKPKUH
0oPYPwhSyvmT6so2Xr/YB5Yx/KbrSK7dMlbxQ+9ct9saKkaioVfo7OvgOY3fFg9k
Qs0RwtRpE1TjaSJw7ScwlaUR7GYUrcIBuCKROcZJPTQaVSM537SOFQXqUn0M7Wfu
QM4545j1aULGnDzbP72fpk/icndS8ArmvAW3JpIe+HFk9IxBuzUh4HKHzO3Dny0l
rKOiVmeztN+a8mipfJRTveuZs/QykCugYkafg+nB9GOTjyBwZzTD6IfW1LO3UZLt
-----END CERTIFICATE-----
"""

SSL_TEST_WALLET_PRIVATE_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDkLNTI9jghjYaX
RMvt/3oFVDZ8FUraVUU718V8vW5NF4OrI7HYi7EgS4BnRh9CfU8r+mkPxPTYJ7kg
jKOcdNGw1ARCiIIl95gw6ymjcXZ7isLCF+79kJNQSKq6lQvrPoKoQpfy8dgjRaGY
7gH3DeX/Oi/QFd3N0C5ZGpyzE7+VmONggzoGk5MyLbBCcKcOsBQUqOR7p2bEYXDD
P/xl7+u3R2rhWVsp/E9W0eJJmtiVwYrJy6sbzcWBxjCM3Rv4NZs9tTH19EHWDJM4
whHgnEiB7eXz03+0tELhnwkrrm+a0qC2uVqzG9HZ2/hVY0VmPyPVprAihsAPLyJl
npArCs4ZAgMBAAECggEAAr1zFLK4O9bqPdjKpiICQhwfx1+uFW8etLhDm9refziA
EUcNdK9AwkWF1jemWnMMx1dreZAA7LOVaoml0VQpzHjPUEk5XuFZR4Uba+YJ6TPi
YNhOu2bIDhfBTRpLGVkX0pNyJa23zbyhUyfQiDn3gBgfyNzqW/VbCSDjrtbW3yIA
ES2G6VFx1mr/FdWpPyr26rYFiqxdpI3igUZmDsucJcW39d+4gWz76Yjs1lC4Xm/Y
ScpZoMJaGlUxa9SID7Xuvaav5CtuiX5N0ZdYdmpGV30WPVfM8uDGWp+foAwuWCK9
Onc2uAsCS81n9qKmrrcoh9bKzan0Ntq+EGCMkdhaXQKBgQD9+jbNeTsgA6+MrF6e
sOKpjgpZ24P5bD0SlK0q6hq45yts7bunUJidEMrhJEBQ74Ajs5BjRNkfAu6/b+nI
dnxu+8lIet5xLw9SFXeYmE5W6mXknFoe1i8QR/T4v6Kt01NdQC84IqLsogHmYJpc
aF1LD6trGP74+3ZBoCo5yUofdwKBgQDl/gOH7TBjnNGS45IrOkcLpd3j2mUINNbu
O0p/H49H1Qg8igB3TGGifbRCxoOeXkw5/aCiO80Cp2fy5QRGvec3c+BZwEQZ3bBi
rSigZQPbjKhMBINeC9Mw2CBjJtK0VuvKY9q+8X73K5Z8ovAqlIqXEQR+dufG0Gbu
uD5bdUuC7wKBgHf19mqpB1dAxmtQg0S7UeQ6VgNJXxWxnUsodH6fos2RSv6hb5BA
zkTpyJn9EG/qIAE88EcjHta6AODlUGxCItYdEV6twmF9k+P2hc3Kqr386vHHM/36
trIe+sN/aKxn86lJBsSh/4h7oSAaou5g0SgCF7p3TP93bszihO9UdzFTAoGAX9DW
Wb+IBEfly6NBVv79cC3W5kErDCMvU6qh25ojUBLBTq9TiF/q4Q4rlhIr7UNt0E8I
p+3v9+YUWU3t3Sbqd+Cvm9SMypXgEQwAu+m5lLLhvmG29OxKPLQdshEPgRAhRX0a
OahUc9bV5/Ddy2982Xi+fY09/EcASv25BNM19UMCgYEAuTkovlDqkBvGponDZ7fc
jZjuxXAphxHKcV2CLigByylB23/baHZwHA6XbfbjTEJJJt/f1+GsMkJne/aVY4ZA
y90SrWL71u2PQXCEk+ZwsYw4giWzTJxZgjD+at2rl2XkLXsTVZ9vMTVIwGwJ4sWR
pZriXfsrE3WjsKTdKXlba28=
-----END PRIVATE KEY-----
"""

SSL_TEST_WALLET_PUBLIC_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUIYvyPYsDrigeLVIkFXsvpHrP/F4wDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyNloYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQCpwUvZ+07XGeclurl24s5mocAP/pmlUQU50unzsPRWarrt
4DIjFX4CUErlCnwGKff6sXkSNzJOCNQ4NQXIJ5imbEvx7d5V80z/5Phus2JsY4uf
IZ/LidOk4tSlUpLDuYURCziqy4fljEY4M58zfgCBHz2aBsLE6LJ7/WZSI6LcXcs6
p9UkVY74uSfnFjVN7W7ivNutdv/vo2qsWPHojn35yYV2JEBje5LMtw+7SDJ8ljMc
kkVh+67msxiLlmxhZadA1eTf31kyceW3PcXA2rGqTMIcdb7REjOhA4kPgKV9R3lA
C0wqWEvufnkh2FuiOjI0mcYguRdvRJQooqMDr8KhAgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQC3nE/WNyDiL0+UqIamE2ER
Xii4bQkuOfIFQKn13ciD3hxBI25sDS1T7ssAk/XvKxgMij7jx7vtRV2vJg905c53
2+QxDkkCOO1wrYsvJfCNJ5yz2JkO0eXG1RLmIViixLoyipjEDwSwPM7SpK2LngsL
teV/CKkQAmdOIXB6e3KMv7DvBHboGmm/cv3JrKdLxcQd80HigqNR29nPAJhBx4T2
VZneCNnrErYn+OsaM1TdlyIoTF15Aq5fJY5hfK3v5xLv7JP6X5XqXTVh8Bua/A9B
7pWnFtxNcMr2NbC5Jfmu2Zgc7xTcB1M0bRVSLO4ytMFnBvm451K3Awhz25CRF5zg
-----END CERTIFICATE-----
"""

SSL_TEST_WALLET_PUBLIC_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCpwUvZ+07XGecl
url24s5mocAP/pmlUQU50unzsPRWarrt4DIjFX4CUErlCnwGKff6sXkSNzJOCNQ4
NQXIJ5imbEvx7d5V80z/5Phus2JsY4ufIZ/LidOk4tSlUpLDuYURCziqy4fljEY4
M58zfgCBHz2aBsLE6LJ7/WZSI6LcXcs6p9UkVY74uSfnFjVN7W7ivNutdv/vo2qs
WPHojn35yYV2JEBje5LMtw+7SDJ8ljMckkVh+67msxiLlmxhZadA1eTf31kyceW3
PcXA2rGqTMIcdb7REjOhA4kPgKV9R3lAC0wqWEvufnkh2FuiOjI0mcYguRdvRJQo
oqMDr8KhAgMBAAECggEAaFt1ZvdQm3nIGPC2jXiXDI8JhIuvJuss/ERGINK7Etkg
O5ZlHB5dTczQjgepAR0R3qL13BXkrgZNeJRYDpkRBdZzxbHGyi39Ox8m/t72dc2o
itZf5v+/BZGQymV95icJv9WXK6Bd1ecrT+ekSkJ+yuJKu4LGf8jR2NmJ6psPxso9
oI2QdSpxCyCJvELbapgXlTxKEZ+6pzxf9Wx1/bjkZyuHRCEJ/+lNq7io+L4Tjvcu
1wzpsqNJHsQkYIJAJBd/rf5M/obxv88jughmgJUQiau0QUjSt0Lq7sXopYLBzU82
ETnj1OTOQLsv42mc/oQauhFw/NeADPP/mIH5iO7cBQKBgQDdJZE+w7cThPO+V3li
8gUb0W17qgiuSnAknY18JW2h7Rrtg5AnmGM3ao0aMyzOFAXuJ4bkiwHC9T9wB9On
VI2HwLzpJxHBmxD8griIo5Vjzi76oIvFkb3ibVkmLRnC6jSLYaz5P/BsXzxJAASt
U90N/jqEBBW7iZSz/TX39ExM9wKBgQDEgkT1oiFhrSn5G4hDDWSkIywWvrMzrfzh
o5X7OO8X8Vwe+wVqNwlZ6/6obbY4cBhEaMXpHMnspEx6X51gzKuR0fA8DUMXG1dO
eB7vODo/TEVXHKwHD4YEhclvoMY2qGRPW08ppA4487BDKkmPNVc+SdpJK2IDoTCJ
QvGW1Er/JwKBgB0f0HQapGa+sLcVoBfm1cNnHmsV5pTFmuVHlpWN/FVB+7TiCb8d
M5vdvX2A1drCClHmBL7ei7nYQKWJcldsLEN/n6F5Er6TpHYM5S6hlJATXF6HfEDl
w8MpMX90mxrva0Ib+ALPZ+Nt22ulw/frvoYUQDKYsyACq4HUzCG+m7nbAoGAFztf
c7rLP4T9ZVn/7g1zTIRr/fRls0JqlzKD1MOSYL5EKdV7emcvT9Y6sSbnWBzIga3x
V/HzXWq/L+iF7p/D2OV9BVx8BgtRcxF4dseq+zjFKdtV6y/GpFo8ylmzlVqrIUam
QUIH/Guy9v3U3H1t5wtMJ0JdwBgaaN/lN/O5OhkCgYAxhqU+/pe8kF/cK+W8R4Ea
JcN9pXg77e3WR6+1tKCutXqlbmzL9bBRyjxXtDvAt1EOL6yCE+qHFeoucjKnxyFT
ksw7ARTebaTDekf0ClkouZpRtyJ3mlL7it0bmm4ySZgbBplEFjYcY5cwDSR1heI/
DbL+N0f47P0O9Z3a1Uvxgg==
-----END PRIVATE KEY-----
"""

SSL_TEST_FARMER_PRIVATE_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUSORAd4kBPC4fSPqHEQskE72Yt1kwDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyNloYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQDLIIgg1ILQGtE9Rkza0ieGUNn6wDssvm0fkcpIZXhrYbow
ClydjwDMQrLHF295ZgfkqDEmD5MUeJTxBNznDlZtkvBIRjPN+M7ZnlGJCUTc9jex
U0a/KxrK6ygsaWNzQ8eNaTNOAR/l6j/kuAUC4vKoYKGzLCW45LlKVB9xQDWinpov
nXpA6S5UUI6YxqeriHr2IiLtXSZmqb1lqftTGXenvdnHrJEmer4iYjXHAfMhq+5/
yHCZmpy4IAX39zwAWA9FnYieGSE8KyEqZW4HfF1Fe3V9C6nsZ2gVL1k0sgAgJ8oW
3CtM8tljHCmyxxD9EHSjJAkSnY3OqU5P2+XMbNcJAgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQAijxQXc6ndCfyUhP7DmFCr
OR3jfPd7Bvc5M306CepT4ZGxXrjgy5idkKS8PAdSTMFJ/h3ShkGatgnb/OoOqiMh
YV78dx0wr4/sdEauPHODkQXmtPj+u2Al9ZyYflTLeiMV7JOn8H4oEE+r0Ra3o89P
F9+GOd/jnF8BpO5GUDN0nN22tNid5kIepMNVG0L3iDMGSDMzcXbGE49a8FPc4CfK
24Fd6BZ2YsUM4NWQ97lfGKtCsnZkChwNVkSkVXP38Zvz5H+sHaMyWQ+hiNBlB7Up
OrNw0uq/jvNv5IGwx/JEuYuXXfPd5CvPesk43ycsBvbjyYFSOsdzU55jEcivPQNW
-----END CERTIFICATE-----
"""

SSL_TEST_FARMER_PRIVATE_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDLIIgg1ILQGtE9
Rkza0ieGUNn6wDssvm0fkcpIZXhrYbowClydjwDMQrLHF295ZgfkqDEmD5MUeJTx
BNznDlZtkvBIRjPN+M7ZnlGJCUTc9jexU0a/KxrK6ygsaWNzQ8eNaTNOAR/l6j/k
uAUC4vKoYKGzLCW45LlKVB9xQDWinpovnXpA6S5UUI6YxqeriHr2IiLtXSZmqb1l
qftTGXenvdnHrJEmer4iYjXHAfMhq+5/yHCZmpy4IAX39zwAWA9FnYieGSE8KyEq
ZW4HfF1Fe3V9C6nsZ2gVL1k0sgAgJ8oW3CtM8tljHCmyxxD9EHSjJAkSnY3OqU5P
2+XMbNcJAgMBAAECggEAcRxGcXGk/llQlrxk450O4V54Y4dT7FCF14SJjdLjQXiE
A2hhtmMBYLzrbK4CJynHz25RIA6gKlATMDsy/38eZZnjL3vYMSQRm2DrqlF9BUYe
MSJcTOul2cUk88Yj2PWvU3F3XkKGDrNorOZD9B2IXnag1HMK9nB3NYquj5PfyhNk
tpgX8a8dnb2KQ7a/+3ESFjQTo7Hw+NQS5oQIf5KgKoCSunJPm575mrvozWYHmSuc
tAR+jIdZIrKR5D2y9JKuWlrywm8C59IbnFLGCqHnqLekawavA/lAsLqPqwrWGeSe
+ztTTscVnTRY043lthBOp3XWfR16c8LXEeeX87gDGQKBgQD2LrWgHpNtLYortEAp
FeIXu4gpmBYG/jK//Kex/t3rmCR8bRdnK49QHbIKfl+fl0u/B4dsrs2fOZ+qqLA1
Bgzkls+V396rNWzyzcHUzatZMu6B9lnw14Rbg/+ZjB2lKl1CJKAHB2WiUC0hlxtD
B+6MRdNQrpmMNpiwewi5bkJ0twKBgQDTOkR48BnooALz1rogO8SuWVp6A+FjfSMi
4R/skUEBqf2j7hybOnhZexouRuN5KOcjVi5zNSitOtors4Iun62mFLFumgTxPk60
fzEHiBMUaabiXPZQW/k5s2kD36utvol/SnrH0LIKVMoXW+wNO1ZC8SD6QOKwT601
0u0dgEzSPwKBgDDpdOKcUJRHkQU/6eN/2oz2kIYbFn1LMhAdBcCCr9roPo+OKTEx
YWb8j2wwUZVmvQD2YPzB+k6hZ0zD+UZ/rj4YjKPtd9MyaTQQl2tNdbbiPKsLpDEK
0NxR7I24Xgd71E2Y80aSPKo0HdNnr13xDH9IPETye8V0739Y4pHdC00fAoGAZCE7
8kSHU6H+pE6G/t62Vpve6vZJ8tqQPGmRs5gLw9ksdnhasS8fe/OCLqvGC1pbb4Hc
FRr/BFdgstSugqGJNLCch7yVWTLbJm8g89wKh2OqC6Zb0S44T6T/xClUfdFT5raM
y4nfzEvzXO1jUcZuFt+tbVQy4bdzeY9afeCjCgsCgYEA6Ob83zzYHNW3XArnSFh/
rLB0PxEDVQmDRPxc3iZ6iu4bSfEejQskb6qi3QHrfwZIb0RIFsB5jFBnzOqAfnLU
NL87vGYucc1yTsS7sNuUl5Bzj3r/IpbtRyJwaiwhyRFFUzQN6SK+3d/F0i9y31Si
cpQmwDGhmx/5+eYyPVBMxqI=
-----END PRIVATE KEY-----
"""

SSL_TEST_FARMER_PUBLIC_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUPNbZirLECcLXWjdq7AF5vdOX4UowDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyNloYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQCVE9/KTj19nPrT0DaIRmLQBhJCvvMsJnY8Fa8R0hfM+g41
jHKzvriwD0yArxbdj+eKr00ZWM9PCG/TpnUkW33PSya+VQ4iADUTcD36F/5p0sfe
psu1+tUf7MdMGERrRnNwG/xTAo47whrJ7QoIYWjhtiOREjImBjWXRgatT4uLuNsj
wguPTFQklEH53mxunBago7qJLwJTFVJ+hrxMuHAwYHxhdNKA18oVKVcg1zE3JTwH
wcY/n8kvUXK6L8GJ3Cororn53ej4KBUbvrsAs6AXtpwUUQy/H0s1ZkuF7r1nmUH/
zGvzrPTMnFvtRA3yyXxpjG2mJvx0svwqVAVV0HpDAgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQCPL//viWfMURAJWiGJZSNH
uy1UWUkt/Ga5zIdr+22nHPEXTE6H4+TbDKomVa7xJebZ/Pr0zG4Y41wk/l65Qq4C
5FBNiGoLTO3T+6aSCF7iwUoWRW3leCL29TZrX3AG+R3CnYJnJtGpH+vmqb4lp10c
duCxdd/1Foe3V2Hc1QhFRwd3uG9wYJ1VL4ifjghT03Kp8UcPDYY3w4A3/QEjVMsl
A0pgj34t7oiT/K54bWtkWphbDu5jX8JP8+A01CXS9njXU1OXEnRKq/x2OhIFEAKS
eKywXcUoqfNpX0qmTKSahTslCZu3kUtOgyHQMOJIceot1AZ2hgzDmmEL3+DD2gZ9
-----END CERTIFICATE-----
"""

SSL_TEST_FARMER_PUBLIC_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCVE9/KTj19nPrT
0DaIRmLQBhJCvvMsJnY8Fa8R0hfM+g41jHKzvriwD0yArxbdj+eKr00ZWM9PCG/T
pnUkW33PSya+VQ4iADUTcD36F/5p0sfepsu1+tUf7MdMGERrRnNwG/xTAo47whrJ
7QoIYWjhtiOREjImBjWXRgatT4uLuNsjwguPTFQklEH53mxunBago7qJLwJTFVJ+
hrxMuHAwYHxhdNKA18oVKVcg1zE3JTwHwcY/n8kvUXK6L8GJ3Cororn53ej4KBUb
vrsAs6AXtpwUUQy/H0s1ZkuF7r1nmUH/zGvzrPTMnFvtRA3yyXxpjG2mJvx0svwq
VAVV0HpDAgMBAAECggEAFb5zWte0oli+QRzSh2f0y7DHAxNE9sCZaEQlZ+0D6bLj
Va4poMwFtjBVEUP4itKNjC3rifHpMvbhELbrySTLIewtN3/CcvUiyLYLZCoRwq+q
1W/wsJdodKKdoxy7BgadmdGLKTRrOI4kSCWZ3AURPjLJ10QXKnKnaGwfVzIOAY/4
77w/gkoBUxKu0IIz/7lrR+P9nZNQgRQOTNM4Ihj4awoPATzxU8StJ/PHqBk9ak+R
Awj16+EYMqHC9S4E2ApqXuh5JFvPFDkiGPhysAKzTsVNGusQHdMbbZw+T6B0y8zq
cRutfJsiMszxfM6mbDozlFB3Bh4747z7h6disfQqEQKBgQDGeK7bbqNw0JuX0PZQ
cSbfV8izp6zITPcgkoHVkLYUCNAl1nRjajIpEAjEMEUdj3rIvza8peWhPVvQuwG2
xMUkuuosa2K6jEuBTE21TuzivRpfQaOlK1YOTSdysifDGWHe5hykzYePiqM1qbRS
u20OvX/Xvu07Bo90RHXVOSJEOwKBgQDASf0dJvdd5xswP1JqnwRHuEjDFTmKb9Wi
kPMeq+k5vZrxMhAxXauTjyG1kiS3TJV/uG9ftLH8Wlpk4k99r40Pop5ArDWehqMR
5IfEvPXdo6cWVS1IfM1NRyqTag1LH7SU/icLdbkElHR+yC1wUB3mXERqPAjF2Y+c
qbhPaPTpmQKBgQCkTuTz5PSKQSmO1gAVOJfl7tbJZNc2PAGbha7XD6atj15C9PgG
FbTRKeUYBp4xiscryqGWLAGfKx0IAMm6dcyAS/3yKDTkG6GmuXTb1StnywY6Ni00
YFwuGtG9sqAYdLsBvZ+ZEE5aF3xmwMf4dhIjUd60zeu4IgZBSywCCfrEYQKBgQCR
7ZSxswi3stPnYabiU5uj8i8GHe11KjovDWH0PPLaZxJXSW8Qh83WRiGG8kn68Zvj
Oc0MDM2mfctsFHPPJpMe8oK3AfoPPI403gJLRDwy4CfFww6CnHQR2ZhuF2XPRVh+
WgK3p7epyiA+txwEyEhosk0ZckYWIG3krsi5OyXiwQKBgCaxZcvbZd4oDC/Ym60s
rkfP/GfkGbMUMYEu+7T4VWaXRqhxhVXJBLabOzaRGgl0sQN9zGJtrBCKZO4Kznc+
SgpU0cHYnMVLwc0d1wUdoJvX1k7Q2hINuy2xK7iqP1M8UAIo4qx9GlIhah4c3+mz
biiy3W8TXzcBFVOybwpMeAQn
-----END PRIVATE KEY-----
"""

SSL_TEST_HARVESTER_PRIVATE_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUa0HzW3fH6O0kNO3yGndcTG3+kX0wDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyNloYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQCtlD5CM6r5C3//rZwWLmMHcIO3lDFfdSwrvONmMhwlkIDU
/FgLr20ZS6ny7DPSRVuU3jijL00Q6XZqpmmzsoN+RU6VITNuam/gB30E/WfF2yds
ifWtVpE9wM51V1SigEtAIviooNR/CrfXxaljw1wmReWjCAUP4MWJBBFGUymWpBlF
vEo+7VWZ5B4bfstRTZaFWRln/otMh8v3SOaJSmNafsDnulq1JXJz/i2hFfPjgfbo
rGp8bfCWpNmEzJSn+CY7aAyW9eKKR+unWzM7+PEnI2l+5rrq54BfxpMdfAFHlMK4
NpIrJNmnjMLm1VQpm2/RFxI3LP+IDedCJmWpXbRpAgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQBc3mZ5yN9pXLT/0Io6Ql2k
SxPSZc68538f/gjpnlXDxApiP0sk2RvAL3C3E3RCH1KeP0wjcRnOwE3J+BTaisGW
BbSQjQMnGm/zKtkwBaSIIjkKXSRCACEzneTMxPwEqCUgAWJMJ2/vzgmbZcQ7TxHQ
UZpOnDhjknCLmxxEk3cGk6+1SIAO9NQF4z4fL5grfQup6sBeyN+srl0WnUFWfBIi
d/pZHcUCKL+FmUrp6eCKGAFGQiM9TyJ62H4Cs/J0bR9e1asLOwSAunTB8+JnQa18
ug0LdcWQLjcoIMaZk5XIn2wlmFIsTqVXS5i2Os7w8tb/XtdxL+2Qi+Hk0oBmGffx
-----END CERTIFICATE-----
"""

SSL_TEST_HARVESTER_PRIVATE_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCtlD5CM6r5C3//
rZwWLmMHcIO3lDFfdSwrvONmMhwlkIDU/FgLr20ZS6ny7DPSRVuU3jijL00Q6XZq
pmmzsoN+RU6VITNuam/gB30E/WfF2ydsifWtVpE9wM51V1SigEtAIviooNR/CrfX
xaljw1wmReWjCAUP4MWJBBFGUymWpBlFvEo+7VWZ5B4bfstRTZaFWRln/otMh8v3
SOaJSmNafsDnulq1JXJz/i2hFfPjgfborGp8bfCWpNmEzJSn+CY7aAyW9eKKR+un
WzM7+PEnI2l+5rrq54BfxpMdfAFHlMK4NpIrJNmnjMLm1VQpm2/RFxI3LP+IDedC
JmWpXbRpAgMBAAECggEACGCePJ23w7tNWy6q2Ns2Rlak1MhfNac3EYlVREpo11tJ
DH59VVsLHexr8GB8A8r7J40uGJog0w8hevY7JcQY2pBHwaTPkaWrbpmN7B660m7I
UVG7PLlv2xYiIMGtQQaGGztU2vagKt1+j/hnO3xjRymacqrha6nCfuFmYAmFeVKv
115atZR/MRuDO6q0yAghUj1Vapb7DEKzzYdbHMPlytzqD1Th6jnjXA7Hd5Kfc2Lv
kei2eTHVWCzU53+K+WhgcAhINxtkHz0L5zoVC0SI6mGPTFTRXfvt7lE02eOPodfB
1G2L3lilB/bVwaiXYlGeBH/D6jYBC5I7wTlOqILbAQKBgQDXSMomRZ8YFwR3mzdK
k/iP2YWu9UoA54/VcOrC+zq4PnYKQX2TY734lrs71BXEojsm3p8chKSsxjWyuaz9
UbD/1HaXEEwdGCuzJllQiM9JTT2rBTkg5HDhm/nbNaoboxBm7V1SwVEGy7mJtVt3
NOJzwb2/hX9T59ra7PpyAuJMSQKBgQDOaEA8vtpwiGa0aFPE0+ueehQHyyLN9M/Q
TfFPK2ZONu2v6Ws3PlG84i/2jCnyERaozEZqD2UF0RFCcmGtb76K+OSmtBmbJXNL
01H9dhcbRb8VKpgtllffFr9uaHl5EzSpzK4BBUN8C9Sz7tZzQtNXq33fXMiFNzP+
Nn3zBHznIQKBgQDMoMZsrF51UmOPoHxkqdNoP9TeoQ4PYAsKUQMEBDIjMFOYmflX
oEXQxM0BKCzss1tQLejE/ZtdEiW2VOCGBCEeen+iRP5j5TacWUYp03Bb90w3g4Zy
qlBVUaGjaBXhoRQVEWdUIqX2tKwNpdFjtGPOrYfDRIvrYAVZdEj1F6Kr6QKBgAWq
ePDx8D8cj20uW/ZQNuyPv1MDcX4j1TyLly8sKs/E1Dt69dV7YXUE5HopGNGrRGr3
yIsKxyQkvAuN5j6DjcB02pn04asPmR2gvGRvxGycOoWTOMAvm1PlZPXb6lG3hD+Q
/cnLYjHahUk3Ki3ZzMFgVME34808WbIFvulX2zHhAoGBANYQhGmVub1/Q2dMFpnr
yoy0S3udcyoS/e+NqVN6uIH5f0YkoMrPhiayWvZY48lKCZkClvPcHwQmZspjKzqA
TXPR03c+XvrdhTkSEzqR7MRfYLkd8viJIVY5uRuDuEwFhCTR9oTJ3p1F4hnBUcPt
YB/7MK+H1kbqXiJzXBCzmRh+
-----END PRIVATE KEY-----
"""

SSL_TEST_TIMELORD_PRIVATE_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUfogbG84aJo97wy3P0ZHAkXShqO0wDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyN1oYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQCxBstxYtPbm7eb1iRbL4SZCF0xIueUH/gZ5nfj3Tbo9DIn
QcHVbNkr5XxH5MBtQcT8bgF/tgBkj7uuFTymT2EpBrtTbdLCTsZ2eMQIABOQ4APZ
NKDiYb6g95JC7vdmuLfuB6VyvlMCZ/Ffyvow+PCgpT7ElNjMiLf7y6mcvzgNKSLN
JYqrJCf7vT0a4W+isck6/fD9J1RUhE0Xkts5wmpwJQGsRYme2hNy/PmCcEY9rqpi
YOxWWeyLbdZ4nI4OH652JwXKUTijqCZYc6+BoXfjwZGq05WK5NhBZVnlYMd5ZFab
DnXGR1WC9ysv1xkFqpSfPlwSZdZcJzBnXXwhJ4qrAgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQCYInnIgvKBvmX65bVLmhNt
cEUickmBTKOEG4i1yovVcDPIPLGH+3p4Oxng+N9zJh6n4SyCeOou30tRuNEunHOC
PmixRUxM04iNm5lLLdS8dd+kErpX+EYT20amgbnN0HNDRi7+EANXTm2ld9HD7skb
M6lABrsQQdmepdNz6609G0HO/I9rdUy1GaXlwd2th21VyzKmmq28nIT7KidBoQNG
MhTjsnNrZekjW/k3sJA9nEhyERmdsApb/TlUV6A4ttQZOqPV3ClkumqQn04jLEhg
dBNTzK0UEqdVXrPRpJBa/gSkSsCWXjMhwY60pHDsDmnOQH0kLQ5KzPU7IF3x+l3M
-----END CERTIFICATE-----
"""

SSL_TEST_TIMELORD_PRIVATE_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEvwIBADANBgkqhkiG9w0BAQEFAASCBKkwggSlAgEAAoIBAQCxBstxYtPbm7eb
1iRbL4SZCF0xIueUH/gZ5nfj3Tbo9DInQcHVbNkr5XxH5MBtQcT8bgF/tgBkj7uu
FTymT2EpBrtTbdLCTsZ2eMQIABOQ4APZNKDiYb6g95JC7vdmuLfuB6VyvlMCZ/Ff
yvow+PCgpT7ElNjMiLf7y6mcvzgNKSLNJYqrJCf7vT0a4W+isck6/fD9J1RUhE0X
kts5wmpwJQGsRYme2hNy/PmCcEY9rqpiYOxWWeyLbdZ4nI4OH652JwXKUTijqCZY
c6+BoXfjwZGq05WK5NhBZVnlYMd5ZFabDnXGR1WC9ysv1xkFqpSfPlwSZdZcJzBn
XXwhJ4qrAgMBAAECggEBAJeSy8rv5ZpZgCKsfkCdNRma8cBKtKI9pT73+JtgI83e
mLrIMOE+68wMGBeuo5xo/fNtdVcWTMvNzdLGWEHGIdjw7KAInrbEoGV8Dc0T06zu
Qh1OVJrBOmm00MUCu052xvXGEkFm+MhMm3173DDmVZIXKuFC2UZ3oaC0xytxBtss
eo/VsopLA8hgjhXo6PEFErZA9qGCu50902kL0L0ZYI7ltVqvLS4p9te+AeFQ6uoL
aiC2ac5jjUqKWh9vEJFfsxzu4vNHZIAsoTMWlO38JOGxa3gh5RS/FI5a2lRr6ohn
ZT3NFllTEjBfH0jzj8re6duTtEQcbhEeykaK2BBMP/ECgYEA4IfDW/sr7E1GsNt1
x7lfr6MkV1Vvg01eSRY/OoPs+4YR0votS4aWbvkIBfHRhm1cBOiD3cXPVkMEf3q0
s/MjerEgR2hTaL6I9YW/2r5IwDsgc2pzxXUAvVdQVacmV9NQaKG+UcYQ4MshnST0
mkw/AMh2vGn+RqokaQnjpR7nkG8CgYEAydaTubt8jZoh9FqK4BSwN9o0CTvc38zd
eYDzmH6H6jf6Ejw5i/uQKcrpqEPq8fKCkPt4slCAPdc8SkqzCA/65S3mnhwECS3i
AZHWxJVIQytzs4kwXsJNgL5z1T9JGobfhXV5i8KitWlsWnsZtjdZsMnAlu0+e6Rp
aVVU+/BND4UCgYEAxLtQGnUOfEMNcIMqRPCQ/aT1f6w1RBfzSBi9F/lmGNDVJ0Xb
kDSB9QQw2nySeLWzjf1pJVVgIRYhh80tLgsZCDTQsqCfjMR93prtiq11szFbcqVQ
gS/OkRhDJHmLqCJYbwVha+ce/MgfUMCDrfqmrXn4R4ibqrEDrCFlHFXi0fMCgYAm
en/jMrkGDdJXUUOUgJ0vqKuu7vimudmnJkxKUCT9I/rKqyyVYToUnZh5+ai6w27c
0PQrmmk4YOYfi6oh6Vn9gwiqL9EdJuAlSHZXN9Z0573BBnBwQD6iQqy2hMAdDIVk
Xgbz/AEk8Jo1ja5TLK4uo+fRXh1BWRC3ggsXlLI8OQKBgQCm3kD+lzjb79vGPHDz
kQ0w7bp4kn1g5tSBlSCL4HBHsF3OmZN/F+ZRtumDSrlEDiEWh+R2pCQ/HH0DdDjR
7wE0a2jY0cp//+OEEK9tmzS6/hqQC/t8RHLRIxMQKO4umVS9LLNRD96+lcNGQ3kK
4ft6j4a4gk8+6U8Kzn4VSjlM6A==
-----END PRIVATE KEY-----
"""

SSL_TEST_TIMELORD_PUBLIC_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUT43GvhVmx9CzguV2nwdektqBaZwwDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyN1oYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQDRiTszw1IkIr9n6KjMvgS/9I+p+La/NwfFPsIWkTE6cffr
LIi9H+yTMTM3tbNXM4JhvqdeN+c2mDAVjhoi+AAQH3gkpXitxD4ZjYzCCTtwd+q0
gpCKLPOmKxYjqCcNkmEc70g/QOs95HyDdvLL1G1sgMnhldGuc0a1HX0Te9nE7KkW
40Etk6lhEKEa9o9rEjAL84Z6kizKELOtjgd5wM3FaAMB/UIhf+kDxB5vtAhsKewb
2Uy8wMpXJW79cqfLxgjDhd7LEZwSba2Z+XRDD+B+NuC58cv8H8y6b69Rwjmya50X
K1gW5/aZA2+mo9NlSAMdlOM5ntgd2Cbh0zg4jDPTAgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQC//83StmG2IlGISJqGVwSj
B+Jl/eodYO1iYuWtCfobI/WZEz7Noqtuth9U2Pjc/VDImy+w/x6XNPTTa0MgUnqi
/GHG1qRIefWrWp00C7fFbrJW1llYv/AFZfgYZB92Vr2X7RupnQOY2a/XwT8dzstU
ZPTNK5wV47MmUp+u7p2Q24ywS+GuQTK7IZnhQjP7ttKKBgdBp9evHuT4B3yl7qUK
JWb3nAreUSESWkumSXlted0sDQQ7ahilzHPkemRgJZotbQID9sV7WqHYMCRtZENX
53jFAQFtxj7mjjacvwWs45XgEGsr37LjCBHUHujVEccfGXN9+LRrpS6pKiyJeMg1
-----END CERTIFICATE-----
"""

SSL_TEST_TIMELORD_PUBLIC_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQDRiTszw1IkIr9n
6KjMvgS/9I+p+La/NwfFPsIWkTE6cffrLIi9H+yTMTM3tbNXM4JhvqdeN+c2mDAV
jhoi+AAQH3gkpXitxD4ZjYzCCTtwd+q0gpCKLPOmKxYjqCcNkmEc70g/QOs95HyD
dvLL1G1sgMnhldGuc0a1HX0Te9nE7KkW40Etk6lhEKEa9o9rEjAL84Z6kizKELOt
jgd5wM3FaAMB/UIhf+kDxB5vtAhsKewb2Uy8wMpXJW79cqfLxgjDhd7LEZwSba2Z
+XRDD+B+NuC58cv8H8y6b69Rwjmya50XK1gW5/aZA2+mo9NlSAMdlOM5ntgd2Cbh
0zg4jDPTAgMBAAECggEAH70guZOBcrXMtmmYgALcZ1MdG8rvq4EjbS43agGuKkMv
IXFKeRNH23fdYTflpXTI8BNX+L6RCET/K5StwtQ79jU+Fpb186RBH8/AHXgWh8+y
Pot0Z2mtsmLeZKJI4BZnHWHlWKd1updMgQFYf6V6ua+8ZK4z56/Qawi/dF8TOm+0
djKcpND3Y8OatslLv/HshAaXbRRTIDpP2WA+J056xmswlC4m+oJZ+qn9tNi7BA+d
5rBSxXi81TG4tx3hlU08Mkbf9D9i3Cmgq7RQMYfwOcySqfslUq8GicOGUBF210nq
HuDY2bA9NLIpmZ42PArLRWXTptxjvU81FkHwRPw+0QKBgQDp1TJj8KQHkHjp4PlC
mbYp3SCycLFpK/O8TUsL/bEip6zMoOOyOPqtLXPPwWvmqzJg39vguKrrUBH6RQQd
w98CBGCCrwnLz3rnEEUO6pMJ21bqMANDtUZOvANkyD9vIGpBRsTt1JwKXnj3Ei1Q
qHdaDKNlVu/oKiBonKuSrVLnKwKBgQDlZmK62etR9J51vXUtA8IVCcnyCe+c5Sye
KB5FozECshePaqYAOZB9mMigM58egoRtFHn+PZsce5lMn7YVYsjxxIIQB+7FNcIK
P9JdTcGfOVrBOF5RCu8510Zay1QKHnRWgcxc8DxtP72Z+zvl1dQ2C64UeJ19LR+v
e0IKTO6R+QKBgHfvyaPnV0sl+E8F/PQDQaNhb5b3JJhsWd04zAh/fG7pEEH5ODE+
9p0DFkb2z/CF2RZFXFN8hPajoET9R2o5AFbZheMiAuVOK5z/BFztRrQklAUU0WfW
QBS8bQUxjQ/j0Xxf3zyZ89uBr4wS/7lCX82Jc/nTyMQNb4gY7AwU6NP3AoGAfJ48
MClF7sWmd2uuhf+upWMl83h2VJMiw+AjYc0fSMmahux2tVSQK8qd4nlojVh1vBQN
mZG5+6UhSEDS15dMdho8VZ0ZlsR3Xr4A93LQJkEwDhsjEX+RKajKrXQbeUvGA2CL
tklDak3gIBAdH+QjXiDGNpS3aVLkDZ416AaW63ECgYAsbUnFFcjUbZBWo1eO94sj
gED0opmVfKY09FjEdnCv3CSCvU5lRHqHMZ8YXN9yJcF6IzkODAIbM6xGaERVZBjQ
Ba3A2mS91Ojb4Ub7CJ6HNKQy+KLCLjBcNmxk8g4ENIkINt07gZL0wlHUe1JDT24x
Urb8MwQ5SGZ9jZ+R336txA==
-----END PRIVATE KEY-----
"""

SSL_TEST_CRAWLER_PRIVATE_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUaD0m6kjEe/kX8KV86Tm3JMOXw5gwDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyN1oYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQC6kaAaFDrrIxHCuID22AfMrV7fVrB9F5h0uQP5KSawigxJ
BHqs9gIjPi7ur9nFGxGFjh+cyFF7kkWbLOJpABEu6J1DC6+MPe67rnQjq3IEds8d
c4ToidqfP1/Pgl4uOfV0MJpYF77Vpc/P2SHApjRIl7wCPxBS50BZkPaXbobb5e9r
3QSFpyLsvs0jeu1xp4w7DBdJsiHY/Qh3ekvUAH3A/tC/kQ97K9ZndgIQflW+OO89
FwWS9pKLXkYbKejhbaQ5D6wP2xcvY4C093B8kpaeMA9DCW8tUATGGTYaN6MUhNt9
d0LQZ0R58uolJW2o2Qv45TokYoHlsuGbDcc11ijDAgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQCaugeA7XZuF/JeC6T/cDGq
c5Y5pEBuhvNHj6aESm2FvuRIgXS6djo1YZF0McTiLVOtnUqDBSl1h/VH1e4n8zj3
MAVMPfXbAByexDGjbEIo0/aLmcUAAy3h/HQYmkX+Ge5Bm0MCszSbM/YqMPV30rSz
Gq/KfB8s8QQb7T2sS10VTlIBL54AjEgnyunR3vPjx0rqfnFRHdQoD7MdUwOEq3qE
6FFzpmp/fUaValfF9FS8w4vDq13LUY7OhphmW8mJHJ6e7GcUxFPLKs1oNpsMMPJz
wd4te+SB/dQ8CH1o3xvvFirUiPNz1wXRziJSO6AqjNXBMe86qnELwfXohI5oxUl9
-----END CERTIFICATE-----
"""

SSL_TEST_CRAWLER_PRIVATE_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEvwIBADANBgkqhkiG9w0BAQEFAASCBKkwggSlAgEAAoIBAQC6kaAaFDrrIxHC
uID22AfMrV7fVrB9F5h0uQP5KSawigxJBHqs9gIjPi7ur9nFGxGFjh+cyFF7kkWb
LOJpABEu6J1DC6+MPe67rnQjq3IEds8dc4ToidqfP1/Pgl4uOfV0MJpYF77Vpc/P
2SHApjRIl7wCPxBS50BZkPaXbobb5e9r3QSFpyLsvs0jeu1xp4w7DBdJsiHY/Qh3
ekvUAH3A/tC/kQ97K9ZndgIQflW+OO89FwWS9pKLXkYbKejhbaQ5D6wP2xcvY4C0
93B8kpaeMA9DCW8tUATGGTYaN6MUhNt9d0LQZ0R58uolJW2o2Qv45TokYoHlsuGb
Dcc11ijDAgMBAAECggEBAJZNDTsVQyX9GajSNOsnvJjSrtSkJQiRwrt99cp7sXSV
sjH8zsuaYLx9sxeNSZY2KVZ72dHXu3UesL7DWR8X87/jnBXQSztjBXnjoCLAUtlv
0Yk7cD5aGGskhg5JS5BYFvrk0OLZNl8t9o3Oshdejk5RFyCEJ6VyMXA2jcIPQ8vQ
QIHa98EnbtBgeW/eYEYLEpMvII9v47KfV9NsMYuLAe/m0/HHzORxo1cPO2MoMlg0
xJLmETf/r13LIh2SMD48zxDCCGvlXXibaUntFQhae03OxvFFnq3bisrXK1BU7aj2
Q7H6wS02+7uGe+aQVIuFSG1fMQBptBfJc6d+0INWGpkCgYEA2yFr6h+RzMyjMqsA
vMR66CHkPnu0OYa9wbam4iKImJgKKCGi+Sty9DSHmCvXyWtoQ/fvrytmVDTzXi0D
XvKhdoc141jojITsSIuRO0rHi1F+LUWaArVhNzQtZCEQs3qWDVipu5GACf3A/Elj
UwQW624ZckLNywaEI0K+qZGGXTUCgYEA2fWtpseMIFlHNY56Hx818Bxs11UuysP+
ebIIPEQ33qr9qxxvd9zI3H5RKorPVpygk0K8YgvNFr2Cb/zooDmvuXjX5t/QVjPS
a5OKqnMw030sIEbkKGiyaxIHy/uL1DiLvK6kJy/kBNJJ4AZRy+t6crm5YzuG35+N
9N1bVGwixRcCgYBhJhUQzAQ4trTXnsaJ6dXPmk71gKRrKJhyDEc6VDMY67b9CcSW
ETQ6nhtLVIyraKnmEEK791K7nGoU44HuE0WQJeu3KlCXE8spcm7lyYZj9rIo4gWg
k8dQ0RoanSopV/y0WA2P8bbBNzXa47JcOKDsqXgwlvtjujTU6R9cT/8wzQKBgQCY
nzsY1RRfNoTxkLIdBtrbJtxkMIbSf0m7Z5nysYY5ypxUbFX1pcmU9HLbilXDfWvH
kmydb0wOR2eGCZ/PSnWtN1xfk4usQR9wKuFnl7+x6C208E8lqKJ+7SI+iQcR9QKM
ffH+ar+NTL9kOqieVWbp3Ple7jj0cCKUO0iPpiT2wwKBgQCMTSD04XOEcm1LBC1P
LxLYZgm0UC/Lwqd5exH9gDP8LT8KC9P46woAIj3jyTVVelQr+7YD5uarFOE3s48M
L2wuBOGt20Av7tQofrx+SoVi7S6yJOJ/bPv/VUj08+Sb1kq0fHo73t90GO/sMeEZ
1ghMH6lVfEjpUpeZLj5iB+icmg==
-----END PRIVATE KEY-----
"""

SSL_TEST_DAEMON_PRIVATE_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUTYcm+E1jiGL7UEiopTFGmSwk3eQwDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyN1oYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQDD4xmVdRUqCRCDRebD9nds1h1mtyutoeHfruSn4PiEx30Q
YSzGRszSTvM+PwzL6jug6CVmlfWzLBC25unegeZhjlhoMkMkVavA1bZQ0sx2t2ll
wqFMhk0BvfQ0ftQ0BEgHpbll361gZGb7sLB0kuh1LhRE6uWpkg3WJT36DwzkCJ+R
YgAA63J11uLhMVk22bQ9UDIlmlL2Kd0M1sLrdPtF7h2wB77RirXpH9RxPilPWTwd
t63eHKetGMwmeCHP6VHWc3mtmnYCcEf851HXr/VYYdwn/Egbn5NWU9MkyG4U6Jw/
7iVRvf8XIv6IGcwY+qB922OjrCxsHYCWUbfwiaFXAgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQBFYpf2hnFIOfEEKFkNni9T
QK//s9W2Bf2hwn59TC6tvpN0pIenfqZ5A/Evc8PnjaO8UY+rWsxRL2YZoDEABnQb
3x0VfnZKQLKGju6JiVJWSn5F5Ilj2ntglHsAgQp4QBEMbIwfStW9AeaCwVoeD34B
/NFUoD33QM6E2yKuRetceeauBA+giBkSFaUA1jeSHfRGeWtuJmnNHvd9iA8cfrSg
gETkXKUyTYkS7Afi47oCMblmuy1pKOnQsirih8Vnic0Wn46bObLn8lt3k1d0+G0F
Nx37aAAP/ArHTyRh0ctfw99aTDgOm5v46NZNLPH9z7NPTtN0tz3r3C2nT4SUB+qq
-----END CERTIFICATE-----
"""

SSL_TEST_DAEMON_PRIVATE_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEwAIBADANBgkqhkiG9w0BAQEFAASCBKowggSmAgEAAoIBAQDD4xmVdRUqCRCD
RebD9nds1h1mtyutoeHfruSn4PiEx30QYSzGRszSTvM+PwzL6jug6CVmlfWzLBC2
5unegeZhjlhoMkMkVavA1bZQ0sx2t2llwqFMhk0BvfQ0ftQ0BEgHpbll361gZGb7
sLB0kuh1LhRE6uWpkg3WJT36DwzkCJ+RYgAA63J11uLhMVk22bQ9UDIlmlL2Kd0M
1sLrdPtF7h2wB77RirXpH9RxPilPWTwdt63eHKetGMwmeCHP6VHWc3mtmnYCcEf8
51HXr/VYYdwn/Egbn5NWU9MkyG4U6Jw/7iVRvf8XIv6IGcwY+qB922OjrCxsHYCW
UbfwiaFXAgMBAAECggEBAK/Sf3wvAzgfurqZW3A5ISiHZwxzDLlkvCDSElq9C1Pi
2taA4nd1xRJf2uTcIthE/hCHTkqt/0M7IiWJThFx9x9JbQDZXHqYivki2enhy7Qj
HG9CKxVM1oHhxff4fu/Rh/WVQru18SC7/dOb3EZGNnA3U+ooDMwPVGwKMX7pU2C4
6ofOzP7xqqmlsBA+oZ9ULCqN18bSefqHz0wrGlEFBeGyou+vFXLjnYNqejPri88T
BF49eEXtk4xK2ej0bNzoCuMSEgXOQ28+n4w6nCM5N5LPMWaQY/1sc8v2FsNakXL/
BUli4mgcZ2a0Vk90bJ9PM69arG4EKdORECU1rygXPUECgYEA530+XT37NfOLQgt2
ex4u8ZndpV46vZ/F/i/v/McMKCmuj/704+6hhpwyeen6dtRGuMJAF4TmW7kAq2rT
nonEueBcgAWudVoS7/gGO4FNr+dq5ckz6vqrkIu01BJayrjrCly2j9u0++/mSXkB
obH8C2SYaoPo7t7Rbpebb6vkCIsCgYEA2KDS4JG2/gj+9OOXoDzZpFHLvNbJdFhd
6Lu2LYbn8Q6z4zBize0kXqdytUzIqNw2mh8Nye47lQ7xsvotzPkb9c+Yx+eiJyy5
nFmTlfs2h9E8TAbUkq9QDvC8cElTrfQz6n3nEsjd8ohbUsH3NlPvAbriIlfHUIcW
XkiioJIMl+UCgYEA0fibec3/r+cxuH1XQcOWBxVuo1H+bAOhfreSsjEGCOQN75Tu
IlVQdB339vdRdTmE0I95vRuSKz56qgGi49nI9GTa4lDE9rL2HG5XkN/vTI/XOYiw
LAKlXd4q7nWbnufuYh7IhWJfHmpy8s/st/MOUHM1gOAXh5vaUbr4hWlf1JMCgYEA
yCkZkGyzY9jWE1q0AFgZVY5KrWrc68a2xtOjCkAL0h2es35C3TmQEHGyOLkA852+
SfwFlp6sqRcM1y344dsPLbqq1ZM+renSexf9mWhsQ2RezXTGN98LHzLrOulWC3aH
/dRljWLSSUYa88XLcYRuY+/VAJyQyuR3E5kTw0APqM0CgYEAn2H7MD7O4llk911S
W016DVnG8tuOD2t3/thIYxU2YJYGnC/fcdGLzzUHhReveb9wRsDU/EHAeRJcaR8W
+yZ2oU3lQhN3WgXcQAdUrShSZ7CCX1yWPwF7HAJObuQOkJUdew27+dw4MFAzz6vh
ne+NcDLDQNP3iJoBJjKkQOldWDA=
-----END PRIVATE KEY-----
"""

SSL_TEST_INTRODUCER_PUBLIC_CRT = b"""-----BEGIN CERTIFICATE-----
MIIDLDCCAhSgAwIBAgIUbtU04ozLF4XldtM40YPkF1DIMKEwDQYJKoZIhvcNAQEL
BQAwRDENMAsGA1UECgwEQ2hpYTEQMA4GA1UEAwwHQ2hpYSBDQTEhMB8GA1UECwwY
T3JnYW5pYyBGYXJtaW5nIERpdmlzaW9uMCAXDTIyMDMyMjEwMjkyN1oYDzIxMDAw
ODAyMDAwMDAwWjBBMQ0wCwYDVQQDDARDaGlhMQ0wCwYDVQQKDARDaGlhMSEwHwYD
VQQLDBhPcmdhbmljIEZhcm1pbmcgRGl2aXNpb24wggEiMA0GCSqGSIb3DQEBAQUA
A4IBDwAwggEKAoIBAQDnZYSeBOBGn94eiPAorxg9GdUoIGr4UUNxrtXTBmX8zZZp
LIu3m+2T+BO0ig6a4SZ7IxD4Ocbj2YP6sYl44F3fNXjvekvNzTE6LaeCvOh5myUj
3h/cCZTMCV9Ja4CMg+xOCBLu+CjyWSkp5Z8kdYz86o7gKNh1eJT50a8pARqyNdWw
Q/YoYTTpfG80GQp31Zb3hzX9fl6dT6+gYuV1xkiPrSuxX4oZZ7ZH+ktIwiFoXGOh
sQu1cLaLHP0iImF1QCHh56RwV7j/RcgqMx/hdzz80rShbUost85ngl+0ss3jYm1+
Z5Ps8u8FRSdgN4H+HQL16q8OGrMZXdnRKUYEiCY3AgMBAAGjFzAVMBMGA1UdEQQM
MAqCCGNoaWEubmV0MA0GCSqGSIb3DQEBCwUAA4IBAQDG/ltB2n5vOIPi90d+GikR
nGu1SR7ALScsbF4w4uIH8UvtMTu4nctlLJWPNuor3s7ylnwv0eMwumtuHYuIBSm3
9umrUIGlwMedCdMNKpvQF/WkXevEQj1azfGmltta+ZrQBxwhHg069y8Ykb84SM8D
5vEy0rJ+zmrvFYeKaxzAjA1sG4bjCiMMiwJ2rHXFjIFdQHMwwYcFQ1FeAPxEe/8T
PGYY561vOKVP6P86swKPOsQn+3MYR0Ehi8vdw5E4f3TcOkyxx5sPmiC/3pq0h4U4
kmLI+Ng3D1A3NzSel2J0mp7RiPmUhu//WZOE3G38+27jGp9GPEM/zlc1gL2EHN9w
-----END CERTIFICATE-----
"""

SSL_TEST_INTRODUCER_PUBLIC_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIEwAIBADANBgkqhkiG9w0BAQEFAASCBKowggSmAgEAAoIBAQDnZYSeBOBGn94e
iPAorxg9GdUoIGr4UUNxrtXTBmX8zZZpLIu3m+2T+BO0ig6a4SZ7IxD4Ocbj2YP6
sYl44F3fNXjvekvNzTE6LaeCvOh5myUj3h/cCZTMCV9Ja4CMg+xOCBLu+CjyWSkp
5Z8kdYz86o7gKNh1eJT50a8pARqyNdWwQ/YoYTTpfG80GQp31Zb3hzX9fl6dT6+g
YuV1xkiPrSuxX4oZZ7ZH+ktIwiFoXGOhsQu1cLaLHP0iImF1QCHh56RwV7j/Rcgq
Mx/hdzz80rShbUost85ngl+0ss3jYm1+Z5Ps8u8FRSdgN4H+HQL16q8OGrMZXdnR
KUYEiCY3AgMBAAECggEBAI9LBnz0eA5EIcC2/EG1bEUqIh3fNV7gs+tKYY90fuO2
TFaFB2CEZvMixNEgTTsMAlBuvqt42/ltUZWFK6R3DKqU6nciPJ8NWla0vu7vHOdx
c+ZqP0B7jnFrvF4y/EAH0eXgihkCBBlPrXYMhCiHwu88MY4OvTzBlz+84cN6s5V3
I11Ui7buknOJMfKEcFkyklqvfXIGwbYniPUWEpmuZmv7TV9X+EYJDU2QrLbqA4Ds
6c4KqVyjXaIdfk+ZbABTVLpQl/qhI/FcBRLhlrlP2nG+kWBgqWannrrmWF1Fg0D4
p/dn50Xqf3noA4VnMETUq7FMKXh5rUs8mphyYcZt4AECgYEA/Ls+Yyn8L5Zt0rcl
dpy2VX9e8wHmV2pt+HurkKrBMbvir1jvSElUWF8H9r9lwwRvq8QuCmdLM4xkWDoA
Dz09YESKn/ZTVh/q6CqOxT3GUqRdWfOhL+n31AO1na8TDoKbV0DTMi3rXnDPYD3/
AOwGS3JrT+KOIG7GZz0JlzJRigECgYEA6mOjQ+VZtVOwqiPk3+tAfRVwhjC0hCpL
itumyACOGKEDmgBLxkqXjzikDB/Zp1d1J1Hm+f4U/vLXuhG3q21A8hMCkqllIhzE
25CUs0j3lzj2hTne0C9dl111vRquOiom3DUaROUePTzCGDGlN3hLzQYY6fcZE56R
wkdWeNIDgDcCgYEA5IKIjjDQDFb/RZ7DCNP5KKTZvO7izfc1J47qOQurUsSG2fSX
pcxnrt992+SCpinErpHa7x0mKZ2uvPb0RtMgQ4K1tJyMDTsesnyISl7oiqCCp2pZ
O3FY2yHffItnt57vxZyfWKecQO/PET3862B88Iqr7Lbzuu9uBLpziXm9sAECgYEA
nQQ4eCBpkzZIUAIRrguLvP+izNJN64fl6VSyCqOMjWU342+1U1Xe5/v6sYCYryjA
e6G7SNd0O0J1T9nUn8tlyYUAoT1HWa3KFohphR0pd62aP69/2xkP6nmaiR8Zfi+E
rtoICgUu17kfEVQYqOs2ZFdkUz/MFb+RR4PAotmVrMsCgYEAlcLcL82ILHLE+5IB
Df/QIDdw3quq6Xtn5u4+LlVHJclOWMH7imngVRIU21dKyxTrVwG/Fe7YntUGnc+Q
U4esDNFlYh2raWgsTa3oxrbQyPaq5P/Qzbp8QrUFW3eMwW3a95CjQRnscxO+1IN6
gqCQGe9wW+ZeGMo5qplhtJURjus=
-----END PRIVATE KEY-----
"""

SSL_TEST_PRIVATE_CA_CERT_AND_KEY_5: Tuple[bytes, bytes] = (SSL_TEST_PRIVATE_CA_CRT, SSL_TEST_PRIVATE_CA_KEY)

SSL_TEST_NODE_CERTS_AND_KEYS_5: Dict[str, Dict[str, Dict[str, bytes]]] = {
    "full_node": {
        "private": {"crt": SSL_TEST_FULLNODE_PRIVATE_CRT, "key": SSL_TEST_FULLNODE_PRIVATE_KEY},
        "public": {"crt": SSL_TEST_FULLNODE_PUBLIC_CRT, "key": SSL_TEST_FULLNODE_PUBLIC_KEY},
    },
    "wallet": {
        "private": {"crt": SSL_TEST_WALLET_PRIVATE_CRT, "key": SSL_TEST_WALLET_PRIVATE_KEY},
        "public": {"crt": SSL_TEST_WALLET_PUBLIC_CRT, "key": SSL_TEST_WALLET_PUBLIC_KEY},
    },
    "farmer": {
        "private": {"crt": SSL_TEST_FARMER_PRIVATE_CRT, "key": SSL_TEST_FARMER_PRIVATE_KEY},
        "public": {"crt": SSL_TEST_FARMER_PUBLIC_CRT, "key": SSL_TEST_FARMER_PUBLIC_KEY},
    },
    "harvester": {
        "private": {"crt": SSL_TEST_HARVESTER_PRIVATE_CRT, "key": SSL_TEST_HARVESTER_PRIVATE_KEY},
    },
    "timelord": {
        "private": {"crt": SSL_TEST_TIMELORD_PRIVATE_CRT, "key": SSL_TEST_TIMELORD_PRIVATE_KEY},
        "public": {"crt": SSL_TEST_TIMELORD_PUBLIC_CRT, "key": SSL_TEST_TIMELORD_PUBLIC_KEY},
    },
    "crawler": {
        "private": {"crt": SSL_TEST_CRAWLER_PRIVATE_CRT, "key": SSL_TEST_CRAWLER_PRIVATE_KEY},
    },
    "daemon": {
        "private": {"crt": SSL_TEST_DAEMON_PRIVATE_CRT, "key": SSL_TEST_DAEMON_PRIVATE_KEY},
    },
    "introducer": {
        "public": {"crt": SSL_TEST_INTRODUCER_PUBLIC_CRT, "key": SSL_TEST_INTRODUCER_PUBLIC_KEY},
    },
}
