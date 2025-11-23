# auto-trading Development Guidelines

Auto-generated from all feature plans. Last updated: 2025-11-23

**🚨 CRITICAL UPDATE (2025-11-23)**: Null bytes corruption incident analyzed and documented.
**Action Required**: Read "File Creation Best Practices" and "Known Issues" before any `/speckit.implement` execution.

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

## Implementation Guidelines (Updated: 2025-11-23)

### ⚠️ CRITICAL: File Creation Best Practices

**🚨 NEVER use Edit tool on empty files - causes file corruption with null bytes 🚨**

This is the #1 cause of implementation failures. A single null byte will make the entire file unimportable.

**Real Incident (2025-11-23):**
- File: `src/api/__init__.py` created as empty file (0 bytes) in git
- `/speckit.implement` used Edit tool with `old_string=""`
- Result: 1 null byte injected at position 34, file corrupted
- Impact: `SyntaxError: source code string cannot contain null bytes`
- Korean UTF-8 characters completely destroyed

**The Dangerous Pattern:**
```python
# ❌ ABSOLUTE PROHIBITION - THIS WILL CORRUPT FILES!
Edit(
    file_path="new_file.py",
    old_string="",  # ← Empty string on empty file = CORRUPTION!
    new_string="content with 한글 or any UTF-8"
)
# Result: null bytes injected, UTF-8 corruption, binary file
```

**The Correct Approach:**
```bash
# ✅ ALWAYS USE: Bash cat with heredoc for new/empty files
cat > src/path/file.py << 'PYFILE'
"""Module docstring with 한글 is safe here."""

# Python code here...
PYFILE

# ✅ ALTERNATIVE: Use Write tool for completely new files
# Write(file_path="src/path/file.py", content="...")
```

**Pre-Check Before Using Edit Tool:**
```bash
# Before Edit tool, verify file is NOT empty:
ls -lh src/path/file.py  # Check size > 0 bytes
# OR
[ -s src/path/file.py ] && echo "OK to use Edit" || echo "USE BASH HEREDOC!"
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

**🔍 MANDATORY: Verify EVERY file immediately after creation**

Even a single corrupted file will block the entire implementation. Check files before moving to the next task.

```bash
# Step 1: Check file type (detects null bytes)
file src/models/__init__.py
# ✅ Expected: "Python script, ASCII text, UTF-8 Unicode text"
# ❌ CORRUPTED: "data" (indicates null bytes or binary corruption)

# Step 2: Check for null bytes directly
python -c "
import sys
with open('src/models/__init__.py', 'rb') as f:
    content = f.read()
    if b'\\x00' in content:
        print('❌ CORRUPTED: Contains null bytes!')
        sys.exit(1)
    print('✅ OK: No null bytes')
"

# Step 3: Test Python compilation
python -c "
import sys
try:
    compile(open('src/models/__init__.py', 'rb').read(), 'src/models/__init__.py', 'exec')
    print('✅ OK: File compiles')
except SyntaxError as e:
    if 'null bytes' in str(e):
        print('❌ CORRUPTED: Null bytes detected!')
        sys.exit(1)
    raise
"

# Step 4: Test actual import
python -c "from src.models import OrderType; print('✅ OK: Import successful')"
```

**Quick Verification Script:**
```bash
# Save this as verify_file.sh for quick checks
verify_file() {
    local file=$1
    echo "Verifying $file..."

    # Check file type
    file "$file" | grep -q "Python script" || { echo "❌ Not a Python script"; return 1; }

    # Check for null bytes
    python -c "
import sys
with open('$file', 'rb') as f:
    if b'\\x00' in f.read():
        print('❌ Contains null bytes')
        sys.exit(1)
" || return 1

    echo "✅ $file is valid"
}

# Usage: verify_file src/api/__init__.py
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

### 📋 Mandatory Workflow for /speckit.implement

**Follow this EXACT sequence to avoid corruption. DO NOT skip verification steps!**

```bash
# ============================================
# STEP 1: Create file with Bash heredoc
# ============================================
# ✅ ALWAYS use heredoc for new/empty files
# ❌ NEVER use Edit tool with old_string=""

cat > src/simulator/fake_exchange.py << 'PYFILE'
"""FakeExchange implementation."""

# CRITICAL: Use relative imports within src/
from ..models import OrderType, OrderStatus, PriceType
from ..models.order import Order

class FakeExchange:
    # ... implementation ...
PYFILE

# ============================================
# STEP 2: IMMEDIATE VERIFICATION (MANDATORY!)
# ============================================
# This catches corruption BEFORE it breaks everything

echo "Verifying src/simulator/fake_exchange.py..."

# 2a. Check file type
file src/simulator/fake_exchange.py
# Expected: "Python script, UTF-8 Unicode text"
# If shows "data" → CORRUPTED! Delete and recreate!

# 2b. Check for null bytes
python -c "
with open('src/simulator/fake_exchange.py', 'rb') as f:
    if b'\x00' in f.read():
        raise RuntimeError('CORRUPTED: File contains null bytes!')
print('✅ No null bytes')
"

# 2c. Test compilation
python -c "
compile(open('src/simulator/fake_exchange.py', 'rb').read(),
        'src/simulator/fake_exchange.py', 'exec')
print('✅ File compiles')
"

# ============================================
# STEP 3: Create __init__.py with verification
# ============================================
cat > src/simulator/__init__.py << 'PYFILE'
"""Simulator module."""

from .fake_exchange import FakeExchange

__all__ = ["FakeExchange"]
PYFILE

# Verify __init__.py immediately
python -c "
with open('src/simulator/__init__.py', 'rb') as f:
    if b'\x00' in f.read():
        raise RuntimeError('__init__.py CORRUPTED!')
print('✅ __init__.py OK')
"

# ============================================
# STEP 4: Test actual imports
# ============================================
python -c "from src.simulator.fake_exchange import FakeExchange; print('✅ Import OK')"
python -c "from src.simulator import FakeExchange; print('✅ Package import OK')"

# ============================================
# STEP 5: Run functional tests (ASCII output only)
# ============================================
python test_script.py  # No emoji, no Korean output

# ============================================
# STEP 6: Update tasks.md
# ============================================
sed -i 's/- \[ \] T013/- [X] T013/' specs/001-kiwoom-auto-trading/tasks.md
```

**⚠️ Pre-Flight Checklist for /speckit.implement:**

Before starting implementation:
- [ ] Read this CLAUDE.md file completely
- [ ] Understand: **NEVER use Edit tool on empty files**
- [ ] Understand: **Use Bash heredoc for new files**
- [ ] Understand: **Verify EVERY file immediately after creation**
- [ ] Understand: **Use relative imports inside src/**
- [ ] Have verification commands ready to paste

During implementation (for EACH file):
- [ ] Check if file exists and is NOT empty before using Edit
- [ ] Use Bash heredoc for new/empty files
- [ ] Run `file <filename>` immediately after creation
- [ ] Check for null bytes with Python
- [ ] Test import before moving to next task

**Import Checklist for New Files:**
- ✅ Inside `src/` package? → Use relative imports (`from ..module import`)
- ✅ Creating `__init__.py`? → Use relative imports (`from .module import`)
- ✅ Test file outside `src/`? → Use absolute imports (`from src.module import`)
- ✅ Always test from project root: `python -c "from src.module import Class"`

**When to Use Each Tool:**

| Scenario | Tool to Use | Example |
|----------|-------------|---------|
| Creating NEW file | Bash heredoc or Write | `cat > file.py << 'EOF'` |
| File is EMPTY (0 bytes) | Bash heredoc or Write | `cat > file.py << 'EOF'` |
| Editing EXISTING non-empty file | Edit | `Edit(old_string="actual content", ...)` |
| Updating tasks.md checkbox | sed | `sed -i 's/\[ \]/[X]/' tasks.md` |

### Known Issues & Incident Reports

#### 🔥 Issue #1: Edit tool + empty files = null bytes corruption (CRITICAL)

**Severity**: CRITICAL - Blocks entire implementation
**Last Incident**: 2025-11-23 14:11 KST
**Affected File**: `src/api/__init__.py`

**Incident Timeline**:
1. 2025-11-22 18:30: File created as empty (0 bytes) in commit 8690fbc
2. 2025-11-23 14:11: `/speckit.implement` execution attempted to add content
3. Tool used: `Edit(old_string="", new_string=<content with Korean>)`
4. Result: 1 null byte injected at position 34, UTF-8 corruption
5. Impact: `SyntaxError: source code string cannot contain null bytes`
6. Consequence: Entire `src.api` module unimportable, implementation blocked

**Technical Details**:
- File size: 477 bytes
- Null bytes: 1 at position 34 (0x22)
- Korean UTF-8 "키움증권" completely destroyed
- Git detected as binary file
- Command `file src/api/__init__.py` showed "data" instead of "Python script"

**Root Cause**:
Edit tool has a critical bug when:
- Target file is empty (0 bytes)
- `old_string` parameter is empty string ("")
- `new_string` contains multi-byte UTF-8 characters (Korean, emoji, etc.)

**Solution**:
```bash
# ✅ ALWAYS use Bash heredoc for empty/new files
cat > src/api/__init__.py << 'PYFILE'
"""키움증권 REST API 통합 모듈."""
# ... content ...
PYFILE

# ✅ OR use Write tool
# Write(file_path="src/api/__init__.py", content="...")
```

**Prevention**:
- Check file size before Edit: `ls -lh <file>` or `[ -s <file> ]`
- Use Bash heredoc for ALL new file creation
- Verify immediately after creation with `file <filename>`
- Test for null bytes: `python -c "assert b'\\x00' not in open('<file>', 'rb').read()"`

---

#### ⚠️ Issue #2: Windows cp949 encoding

**Symptom**: `UnicodeEncodeError` when printing emoji/Korean to console
**Platform**: Windows with default cp949 console encoding

**Solution**:
```python
# ❌ AVOID in test output
print('✅ Success!')  # UnicodeEncodeError

# ✅ USE ASCII-safe messages
print('[SUCCESS] All tests passed!')
```

**Alternative**: Set `PYTHONIOENCODING=utf-8` environment variable

---

#### ⚠️ Issue #3: tasks.md concurrent modification

**Symptom**: "File has been unexpectedly modified" error when using Edit tool
**Root Cause**: Git or file system timestamp changes between tool calls

**Solution**:
```bash
# ✅ USE sed for checkbox updates
sed -i 's/- \[ \] T013/- [X] T013/' specs/001-kiwoom-auto-trading/tasks.md

# ❌ AVOID Edit tool for tasks.md
```

---

#### ⚠️ Issue #4: Absolute imports in src/ package

**Symptom**: `ModuleNotFoundError: No module named 'src'` or `ImportError: attempted relative import beyond top-level package`

**Root Cause**: Using `from src.models import ...` inside files within `src/` package

**Examples**:
```python
# ❌ WRONG: Inside src/simulator/fake_exchange.py
from src.models import OrderType  # ModuleNotFoundError!
from src.models.order import Order  # ModuleNotFoundError!

# ✅ CORRECT: Use relative imports
from ..models import OrderType, OrderStatus, PriceType
from ..models.order import Order
```

**Solution**: **Always use relative imports** within `src/` package
```python
# Inside src/ package files
from ..models import OrderType  # ✅ Correct (parent package)
from .submodule import Class    # ✅ Correct (same package)
from ...utils import helper     # ✅ Correct (grandparent package)

# From test files OUTSIDE src/
from src.models import OrderType  # ✅ OK (absolute from outside)
```

