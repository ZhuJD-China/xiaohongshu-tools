# Third-party components

This project bundles third-party source. Both components are kept under
`LICENSES/` with their full license text, as required by their licenses.

## xiaohongshu-cli

- **Source:** https://github.com/jackwener/xiaohongshu-cli
- **Author:** jackwener
- **License:** Apache-2.0 (`LICENSES/xiaohongshu-cli-LICENSE.txt`)
- **License basis:** declared in upstream `pyproject.toml` as
  `license = "Apache-2.0"` with the `Apache Software License` classifier.
  Upstream ships no `LICENSE` file, so the canonical Apache-2.0 text was
  obtained from https://www.apache.org/licenses/LICENSE-2.0.txt
- **Files taken:**

  | File | Status |
  |---|---|
  | `xhs/creator_signing.py` | unmodified, byte-identical to upstream |

  Endpoint paths for the search / user / comment APIs are also taken from
  this project and recorded in `xhs/config.py`.

`xhs/creator_signing.py` is deliberately left byte-identical (SHA-256
verified against upstream) so that Apache-2.0 §4(b) — which requires
modified files to carry a prominent notice of the change — is not
triggered. Its upstream copyright, patent, trademark and attribution
notices are retained as-is per §4(c).

## xhshow

- **Source:** https://github.com/Cloxl/xhshow
- **Author:** Cloxl
- **License:** MIT (`LICENSES/xhshow-LICENSE.txt`)
- **Files taken:** the signing engine under `xhs/engine/`, unmodified.

MIT requires the copyright notice and permission notice to travel with
copies of the software; both are reproduced in the license file above.
