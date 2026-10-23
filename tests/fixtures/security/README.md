# Public certificate negative control

`aaa-public-root.pem` is the public AAA Certificate Services trust anchor extracted
unchanged from the hash-verified official botocore 1.43.116 wheel. It is not a key,
customer/evaluation source, trusted gold or credential. Botocore is distributed
under [Apache-2.0](https://github.com/boto/botocore/blob/1.43.116/LICENSE.txt);
[original bundle](https://github.com/boto/botocore/blob/1.43.116/botocore/cacert.pem).
Original complete bundle SHA-256:
`ed93d6346236d4f0278f617f5245091f37d001806a49ce42ce0ad5bec858d28e`.
The certificate DER SHA-256 is
`d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4`.
It exists solely to demonstrate rejection, never to supply a trust store.
