# auto-trading Development Guidelines

Auto-generated from all feature plans. Last updated: 2025-11-22

## Active Technologies

- Python 3.10+ (001-kiwoom-auto-trading)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.10+: Follow standard conventions

## Recent Changes

- 001-kiwoom-auto-trading: Added Python 3.10+

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->

## Implementation Guidelines (2025-11-22)

### File Creation Best Practices

**CRITICAL: Avoid using Edit tool on empty files - causes file corruption with null bytes**

```bash
# DO NOT USE: Edit tool with empty old_string
# Edit(file_path="new_file.py", old_string="", new_string="content")
# Result: File corruption, null bytes, "SyntaxError: source code string cannot contain null bytes"

# USE THIS: Bash cat with heredoc
cat > src/path/file.py << 'PYFILE'
"""Module docstring."""

# Python code here...
PYFILE
```

### Python Import Guidelines

**CRITICAL: Always use relative imports within src/ package**

```python
# CORRECT: Relative imports for modules within src/
# File: src/simulator/fake_exchange.py
from ..models import OrderType, OrderStatus, PriceType
from ..models.order import Order

# CORRECT: Relative imports in __init__.py
# File: src/simulator/__init__.py
from .fake_exchange import FakeExchange

# WRONG: Absolute imports cause ModuleNotFoundError
# from src.models import OrderType  # ❌ Error!
# from src.models.order import Order  # ❌ Error!

# EXCEPTION: Test files and scripts outside src/ can use absolute imports
# File: tests/test_something.py
from src.simulator.fake_exchange import FakeExchange  # ✅ OK
from src.models import OrderType  # ✅ OK
```

**Import Rules:**
1. **Within `src/` package**: Use relative imports (`from .. import`, `from . import`)
2. **From outside `src/`**: Use absolute imports (`from src.module import`)
3. **__init__.py files**: Always use relative imports (`from .module import Class`)
4. **Cross-package imports**: Use relative paths (e.g., `from ..services import DataCollector`)

### File Integrity Verification

Always verify created files before proceeding:

```bash
# Step 1: Check file type
file src/models/__init__.py
# Expected: "Python script, ASCII text" or similar
# Bad: "data" (indicates corruption)

# Step 2: Test Python import
python -c "import module_name; print('OK')"
```

### Testing Guidelines

**Windows Console Encoding Issues:**

```python
# AVOID: Emoji and special characters in test output
# print('✅ Success!')  # UnicodeEncodeError on Windows cp949

# USE: ASCII-safe messages
print('[SUCCESS] All tests passed!')
print('Test completed successfully')
```

### Updating tasks.md Checkboxes

```bash
# USE: sed for batch updates
sed -i 's/- \[ \] T008/- [X] T008/' specs/001-kiwoom-auto-trading/tasks.md

# AVOID: Edit tool (may trigger "file unexpectedly modified" errors)
```

### Recommended Workflow for /speckit.implement

```bash
# For each task (e.g., T013-T016):

# 1. Create file with cat + heredoc (USE RELATIVE IMPORTS!)
cat > src/simulator/fake_exchange.py << 'PYFILE'
"""FakeExchange implementation."""

# CRITICAL: Use relative imports within src/
from ..models import OrderType, OrderStatus, PriceType
from ..models.order import Order

class FakeExchange:
    # ... code ...
PYFILE

# 2. Create __init__.py with relative imports
cat > src/simulator/__init__.py << 'PYFILE'
"""Simulator module."""

from .fake_exchange import FakeExchange

__all__ = ["FakeExchange"]
PYFILE

# 3. Verify file integrity
file src/simulator/fake_exchange.py

# 4. Test import from project root (use absolute path)
python -c "from src.simulator.fake_exchange import FakeExchange; print('OK')"

# 5. Run functional tests (use English messages)
python test_script.py  # No emoji, ASCII only

# 6. Update tasks.md
sed -i 's/- \[ \] T013/- [X] T013/' specs/001-kiwoom-auto-trading/tasks.md
```

**Import Checklist for New Files:**
- ✅ Inside `src/` package? → Use relative imports (`from ..module import`)
- ✅ Creating `__init__.py`? → Use relative imports (`from .module import`)
- ✅ Test file outside `src/`? → Use absolute imports (`from src.module import`)
- ✅ Always test from project root: `python -c "from src.module import Class"`

### Known Issues (2025-11-22)

1. **Edit tool + empty files = null bytes corruption**
   - Symptom: `SyntaxError: source code string cannot contain null bytes`
   - Solution: Use Bash `cat` with heredoc instead

2. **Windows cp949 encoding**
   - Symptom: `UnicodeEncodeError` when printing emoji/Korean
   - Solution: Use ASCII-safe test messages or set `PYTHONIOENCODING=utf-8`

3. **tasks.md concurrent modification**
   - Symptom: "File has been unexpectedly modified"
   - Solution: Use `sed -i` for checkbox updates

4. **Absolute imports in src/ package**
   - Symptom: `ModuleNotFoundError: No module named 'src'` or `ImportError: attempted relative import beyond top-level package`
   - Root Cause: Using `from src.models import ...` inside `src/` package
   - Solution: **Always use relative imports** within `src/` package
     ```python
     # Inside src/ package files
     from ..models import OrderType  # ✅ Correct
     from .submodule import Class    # ✅ Correct
     from src.models import OrderType # ❌ Wrong
     ```

