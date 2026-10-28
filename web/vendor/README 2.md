# Vendored libraries

Served from here so the app works offline and the pages load nothing from other origins (CSP `default-src 'self'`). Files are byte-identical to the npm releases; `tests/test_web_static.py` checks the sums.

| File | Package | Licence | SHA-256 |
|---|---|---|---|
| `vis-network.min.js` | vis-network 9.1.9, `standalone/umd/` | Apache-2.0 or MIT (`vis-network.LICENSE-*`) | `f53f833ddb9bf97efe856bb0637d4fe88f39e39999c7e94a4b8afc8de8a1a2e5` |
| `viz.js` | @viz-js/viz 3.31.0, `dist/viz.js` | MIT; contains Graphviz (EPL-1.0) and Expat (MIT) in object code, as its header says | `b9840ae5b70681356c207510db8820ac3f883607740616455d9c7c47d67ea646` |
| `marked.esm.js` | marked 18.1.1, `lib/marked.esm.js` | MIT (`marked.LICENSE.md`) | `930457e5d55439f90465015cc507d3323366e80df5f7a701b61189d4e1046bda` |

To update one: `npm pack <package>@<version>`, copy the same file, update this table and `VENDOR` in `tests/test_web_static.py`.
