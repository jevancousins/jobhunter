# CV Build Makefile
# Builds every CV variant in variants/ to the output/ directory.
# Variants are discovered dynamically: any variants/*.tex file is a target.
# Run from the cv/ directory (or `make -C cv ...`) so relative paths to
# cv.cls and sections/ resolve.

LATEX = pdflatex
LATEXFLAGS = -interaction=nonstopmode -halt-on-error -output-directory=output

VARIANT_SRCS := $(wildcard variants/*.tex)
VARIANTS := $(patsubst variants/%.tex,%,$(VARIANT_SRCS))

# Check for pdflatex
check-latex:
	@command -v $(LATEX) >/dev/null 2>&1 || { \
		echo "Error: pdflatex not found."; \
		echo ""; \
		echo "On macOS, install MacTeX with:"; \
		echo "  brew install --cask mactex-no-gui"; \
		echo ""; \
		echo "Then restart your terminal or run:"; \
		echo "  eval \"\$$(/usr/libexec/path_helper)\""; \
		exit 1; \
	}

# Default target: build all variants
all: check-latex setup
	@if [ -z "$(VARIANTS)" ]; then \
		echo "No variants found in variants/."; \
		echo "Run /onboard to generate them, or start from templates/general.tex."; \
		exit 1; \
	fi
	@for tex in $(VARIANT_SRCS); do \
		name=$$(basename $$tex .tex); \
		echo "Building $$name..."; \
		$(LATEX) $(LATEXFLAGS) $$tex > /dev/null 2>&1 && echo "  ok output/$$name.pdf" || \
			{ echo "  FAILED: check output/$$name.log"; exit 1; }; \
	done

# Create output directories
setup:
	@mkdir -p output output/tailored-build output/tailored

# Build a single variant by name
# Usage: make variant NAME=general
variant: check-latex setup
	@if [ -z "$(NAME)" ]; then \
		echo "Error: NAME not specified"; \
		echo "Usage: make variant NAME=<variant>"; \
		echo ""; \
		echo "Available variants:"; \
		ls -1 variants/*.tex 2>/dev/null | while read -r f; do basename $$f .tex | sed 's/^/  /'; done; \
		exit 1; \
	fi
	@echo "Building $(NAME)..."
	@$(LATEX) $(LATEXFLAGS) variants/$(NAME).tex > /dev/null 2>&1 && echo "  ok output/$(NAME).pdf" || \
		{ echo "  FAILED: check output/$(NAME).log"; exit 1; }

# Smoke-test the LaTeX toolchain on a fresh clone by building the tracked
# placeholder template. If you have not created sections/header.tex yet, the
# example header is copied in temporarily and removed afterwards.
template: check-latex setup
	@created=0; \
	if [ ! -f sections/header.tex ]; then \
		cp sections/header.example.tex sections/header.tex; \
		created=1; \
		echo "Using sections/header.example.tex as a temporary header"; \
	fi; \
	echo "Building templates/general.tex..."; \
	$(LATEX) $(LATEXFLAGS) -jobname=template-general templates/general.tex > /dev/null 2>&1; \
	status=$$?; \
	if [ "$$created" -eq 1 ]; then rm -f sections/header.tex; fi; \
	if [ "$$status" -eq 0 ]; then \
		echo "  ok output/template-general.pdf"; \
	else \
		echo "  FAILED: check output/template-general.log"; \
		exit 1; \
	fi

# Build a specific tailored CV
# Usage: make tailored FILE=some-company-role
tailored: check-latex setup
	@if [ -z "$(FILE)" ]; then \
		echo "Error: FILE not specified"; \
		echo "Usage: make tailored FILE=<filename-without-extension>"; \
		echo ""; \
		echo "Available files:"; \
		ls -1 output/tailored-build/*.tex 2>/dev/null | while read -r f; do basename $$f .tex | sed 's/^/  /'; done; \
		exit 1; \
	fi
	@echo "Building $(FILE)..."
	@$(LATEX) $(LATEXFLAGS)/tailored-build output/tailored-build/$(FILE).tex > /dev/null 2>&1 && \
		cp output/tailored-build/$(FILE).pdf output/tailored/ && \
		echo "  ok output/tailored/$(FILE).pdf" || \
		{ echo "  FAILED: check output/tailored-build/$(FILE).log"; exit 1; }

# Build all tailored CVs
tailored-all: check-latex setup
	@for tex in output/tailored-build/*.tex; do \
		name=$$(basename $$tex .tex); \
		echo "Building $$name..."; \
		$(LATEX) $(LATEXFLAGS)/tailored-build $$tex > /dev/null 2>&1 && \
			cp output/tailored-build/$$name.pdf output/tailored/ && \
			echo "  ok output/tailored/$$name.pdf" || \
			echo "  FAILED: check output/tailored-build/$$name.log"; \
	done

# Clean auxiliary files
clean:
	@rm -f output/*.aux output/*.log output/*.out
	@echo "Cleaned auxiliary files"

# Clean everything including PDFs
cleanall:
	@rm -rf output/*
	@echo "Cleaned all output files"

# List available targets
help:
	@echo "CV Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all              Build every variant in variants/ (default)"
	@echo "  variant NAME=x   Build a single variant by name"
	@echo "  template         Smoke-test the toolchain with templates/general.tex"
	@echo ""
	@echo "  tailored FILE=x  Build specific tailored CV (without .tex extension)"
	@echo "  tailored-all     Build all tailored CVs"
	@echo ""
	@echo "  clean            Remove auxiliary files"
	@echo "  cleanall         Remove all output files"
	@echo ""
	@echo "Discovered variants:"
	@if [ -n "$(VARIANTS)" ]; then \
		for v in $(VARIANTS); do echo "  $$v"; done; \
	else \
		echo "  (none yet: run /onboard or see templates/README.md)"; \
	fi

.PHONY: all check-latex setup variant template tailored tailored-all clean cleanall help
