# CV Build Makefile
# Builds all CV variants to output/ directory

LATEX = pdflatex
LATEXFLAGS = -interaction=nonstopmode -halt-on-error -output-directory=output

VARIANTS = portfolio-risk client-solutions ai-ml data-science quant-dev research software-eng
MASTER = master-cv

# Check for pdflatex
check-latex:
	@command -v $(LATEX) >/dev/null 2>&1 || { \
		echo "Error: pdflatex not found."; \
		echo ""; \
		echo "Install MacTeX with:"; \
		echo "  brew install --cask mactex-no-gui"; \
		echo ""; \
		echo "Then restart your terminal or run:"; \
		echo "  eval \"\$$(/usr/libexec/path_helper)\""; \
		exit 1; \
	}

# Default target: build all variants
all: check-latex setup $(VARIANTS) master

# Create output directory
setup:
	@mkdir -p output

# Build master CV
master: check-latex setup
	@echo "Building master-cv..."
	@$(LATEX) $(LATEXFLAGS) $(MASTER).tex > /dev/null 2>&1 && echo "  ✓ output/$(MASTER).pdf" || \
		{ echo "  ✗ Build failed. Check output/$(MASTER).log"; exit 1; }

# Build individual variants
portfolio-risk: check-latex setup
	@echo "Building portfolio-risk..."
	@$(LATEX) $(LATEXFLAGS) variants/portfolio-risk.tex > /dev/null 2>&1 && echo "  ✓ output/portfolio-risk.pdf" || \
		{ echo "  ✗ Build failed. Check output/portfolio-risk.log"; exit 1; }

client-solutions: check-latex setup
	@echo "Building client-solutions..."
	@$(LATEX) $(LATEXFLAGS) variants/client-solutions.tex > /dev/null 2>&1 && echo "  ✓ output/client-solutions.pdf" || \
		{ echo "  ✗ Build failed. Check output/client-solutions.log"; exit 1; }

ai-ml: check-latex setup
	@echo "Building ai-ml..."
	@$(LATEX) $(LATEXFLAGS) variants/ai-ml.tex > /dev/null 2>&1 && echo "  ✓ output/ai-ml.pdf" || \
		{ echo "  ✗ Build failed. Check output/ai-ml.log"; exit 1; }

data-science: check-latex setup
	@echo "Building data-science..."
	@$(LATEX) $(LATEXFLAGS) variants/data-science.tex > /dev/null 2>&1 && echo "  ✓ output/data-science.pdf" || \
		{ echo "  ✗ Build failed. Check output/data-science.log"; exit 1; }

quant-dev: check-latex setup
	@echo "Building quant-dev..."
	@$(LATEX) $(LATEXFLAGS) variants/quant-dev.tex > /dev/null 2>&1 && echo "  ✓ output/quant-dev.pdf" || \
		{ echo "  ✗ Build failed. Check output/quant-dev.log"; exit 1; }

research: check-latex setup
	@echo "Building research..."
	@$(LATEX) $(LATEXFLAGS) variants/research.tex > /dev/null 2>&1 && echo "  ✓ output/research.pdf" || \
		{ echo "  ✗ Build failed. Check output/research.log"; exit 1; }

software-eng: check-latex setup
	@echo "Building software-eng..."
	@$(LATEX) $(LATEXFLAGS) variants/software-eng.tex > /dev/null 2>&1 && echo "  ✓ output/software-eng.pdf" || \
		{ echo "  ✗ Build failed. Check output/software-eng.log"; exit 1; }

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
	@echo "  all             Build all variants and master (default)"
	@echo "  master          Build master CV only"
	@echo "  portfolio-risk  Build Portfolio & Risk Analytics variant"
	@echo "  client-solutions Build Client Solutions variant"
	@echo "  ai-ml           Build AI/ML Engineering variant"
	@echo "  data-science    Build Data Science variant"
	@echo "  quant-dev       Build Quant Development variant"
	@echo "  research        Build Research & Analysis variant"
	@echo "  software-eng    Build Software Engineering variant"
	@echo "  clean           Remove auxiliary files"
	@echo "  cleanall        Remove all output files"
	@echo ""
	@echo "Usage: make [target]"

.PHONY: all check-latex setup master $(VARIANTS) clean cleanall help
