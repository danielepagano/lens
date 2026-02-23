import warnings

# Suppress SyntaxWarnings from third-party libraries (like pysbd) 
# that haven't updated for Python 3.12+ escape sequence strictness.
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")