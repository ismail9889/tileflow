.PHONY: demo test-model test-eval test-rtl report-switching report-synth publish

demo:
	python tools/build_demo.py

test-model:
	python -m unittest discover -s tests -p 'test_model.py' -v

test-eval:
	python -m unittest discover -s tests -p 'test_evaluation.py' -v

test-rtl:
	python tools/run_rtl.py --sizes 2 3 4 8

report-switching:
	python tools/compare_switching.py --sizes 2 3 4 8

report-synth:
	python tools/measure_synth.py --sizes 2 3 4 8

publish:
	python tools/build_demo.py --rtl --publish
