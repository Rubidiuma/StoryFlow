from __future__ import annotations

import subprocess
from pathlib import Path


def test_validation_response_reports_incomplete_content() -> None:
    """A 422 response must not fall through to the generic request failure copy."""
    api_script = Path("src/storyflow/static/js/api.js").resolve()
    runner = r"""
const fs = require("fs");
global.window = {};
global.document = { addEventListener() {} };
global.fetch = async () => ({
  ok: false,
  status: 422,
  json: async () => ({ detail: [{ type: "value_error", loc: ["body", "config"] }] }),
});
eval(fs.readFileSync(process.argv[1], "utf8"));
window.storyflowApi.createStory({}).catch((error) => process.stdout.write(error.message));
"""

    result = subprocess.run(
        ["node", "-e", runner, str(api_script)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "内容不完整，请重新编辑。"
