# THROWAWAY TEST FIXTURE ONLY

Generated offline on 2026-10-05 using cryptography and OpenSSL 3.5.8. The token is a recorded RFC 3161 response for SHA-256 digest `3c8802794f3df2f526604a15590aecd331decb6ce65ce4f36e85c3820e2ddb63` of the literal `THROWAWAY TEST SIGNATURE ONLY`. Test policy OID: `1.2.3.4.1`. Root and TSA names state THROWAWAY TEST; no operator key or live timestamp authority was used. Private keys remain outside this repository and are not needed to verify the fixture. The token was independently checked with `openssl ts -verify -token_in -in token.der -queryfile req.tsq -CAfile root.pem` before recording.

Operator-declaration tests generate throwaway Ed25519 keys at test time and
verify signed declaration lineage independently of this timestamp fixture.
The old RSA operator-certificate fixture was removed when operator signatures
changed to Ed25519. X.509 remains here only for RFC 3161 TSA verification.
