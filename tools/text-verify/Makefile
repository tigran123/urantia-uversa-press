# Makefile for the text-integrity verifier.
#
# Invoke from the repo root: `make -C tools/text-verify <target>`
#
# Targets:
#   verify         — extract all 197 papers from both sides, diff every
#                    paper, build SUMMARY.md
#   verify-pNNN    — same but for a single paper (fast; <1 s)
#   meta           — run the verify-the-verifier suite (5 checks)
#   spot N         — print N random verses side-by-side for human eyeball
#   clean          — remove all artifacts (re-extract from scratch)

REPO_ROOT := $(shell git -C ../.. rev-parse --show-toplevel 2>/dev/null || echo ../..)
ART       := $(REPO_ROOT)/artifacts/text-verify
PY        := python3 $(REPO_ROOT)/tools/text-verify

.PHONY: verify meta clean spot

verify:
	@cd $(REPO_ROOT) && for n in $$(seq -f "%03g" 0 196); do \
	  $(PY)/extract_tex.py tex/p$$n.tex >/dev/null; \
	  $(PY)/extract_html.py $$n >/dev/null; \
	done
	@cd $(REPO_ROOT) && $(PY)/diff_verses.py $$(seq 0 196) > $(ART)/SUMMARY_RAW.txt; \
	  echo; \
	  awk '/CLEAN$$/{c++} /FAIL/{f++} END{print "CLEAN:", c, "  FAIL:", f}' $(ART)/SUMMARY_RAW.txt
	@cd $(REPO_ROOT) && $(PY)/build_summary.py

verify-p%:
	@cd $(REPO_ROOT) && $(PY)/extract_tex.py tex/p$*.tex
	@cd $(REPO_ROOT) && $(PY)/extract_html.py $* | sed 's/^/  /'
	@cd $(REPO_ROOT) && $(PY)/diff_verses.py $*

meta:
	@cd $(REPO_ROOT) && $(PY)/verify_verifier.py --all

spot:
	@cd $(REPO_ROOT) && $(PY)/verify_verifier.py --spot-check $${N:-50}

clean:
	@rm -rf $(ART)/tex $(ART)/html $(ART)/reports $(ART)/SUMMARY.md $(ART)/SUMMARY_RAW.txt
	@echo "cleaned $(ART)"
