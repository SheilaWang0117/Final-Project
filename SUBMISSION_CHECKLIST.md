# Submission checklist (for Sheila)

**Canvas upload: exactly these files and nothing else** (the instructor penalizes extra files):
1. `report.html`
2. `slides.html`
3. optional: the demo video (`output/video/demo_captions.mp4` with your own voice-over, or `demo_narrated.mp4`)

Graders clone the repository from the URL inside report.html and slides.html, so the URL must be in both.

Nothing below has been done on your behalf: no repository was created, pushed, published, or shared.

- [ ] Put the GitHub URL into **both** report.html and slides.html: `REPO_URL=https://github.com/<you>/<repo> REPO_PRIVATE=1 .venv/bin/python scripts/build_submission.py` (drop `REPO_PRIVATE=1` if the repository is public). This prints the URL, a `git clone` line, and "Private repository: access granted to GitHub user zlisto" in the report header and on the first and last slides. Without `REPO_URL`, both files show a red "URL MISSING" label.
- [ ] Review `report.html` and `slides.html` (open locally in a browser; arrow keys navigate the slides).
- [ ] Share `USER_MANUAL.md` with managers (plain-language guide by question).
- [ ] Report §6 says Ocra's scientists already use the app and that the latest changes followed their feedback. Check that this wording matches what you want to claim.
- [ ] Demo video: watch `output/video/demo_captions.mp4` (silent, captioned) and `output/video/demo_narrated.mp4` (synthetic draft voice). Either record your own voice-over on the silent version using `docs/demo_script.md`, or submit the narrated one and say the voice is synthetic. Upload it wherever the course asks (the files are git-ignored, about 17 MB each).
- [ ] Create a GitHub repository and push this folder (`Final Project/`). `.gitignore` excludes `.env`, `data/` (databases, uploads, caches), `node_modules/`, `frontend/dist/` and `.venv/`. Check `git status` before the first commit.
- [ ] If the repository is **private**, add GitHub user **`zlisto`** as a collaborator.
- [ ] Confirm no real keys or confidential files are in the commit (`git ls-files | grep -E "\.env$|\.db$"` should print nothing).
- [ ] Optional: run the user-testing protocol (`docs/user_testing_protocol.md`) and record genuine results.
