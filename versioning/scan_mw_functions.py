"""Scan FastAPI route declarations without importing the application."""

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


HTTP_METHODS = {
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "trace",
}
ROUTE_DECORATORS = HTTP_METHODS | {"api_route"}
EXCLUDED_DIRECTORIES = {".git", ".pytest_cache", "__pycache__", ".venv"}


def _source_segment(source: str, node: ast.AST) -> Optional[str]:
    return ast.get_source_segment(source, node)


def _annotation(source: str, node: Optional[ast.AST]) -> Optional[str]:
    if node is None:
        return None
    segment = _source_segment(source, node)
    return segment if segment is not None else ast.dump(node, annotate_fields=False)


def _literal_or_dynamic(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return "<dynamic>"


def _decorator_call(decorator: ast.AST) -> Optional[Tuple[str, ast.Call]]:
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return None
    decorator_name = decorator.func.attr.lower()
    if decorator_name not in ROUTE_DECORATORS:
        return None
    return decorator_name, decorator


def _function_parameters(source: str, node: ast.FunctionDef) -> List[Dict[str, Any]]:
    arguments = node.args
    positional = list(arguments.posonlyargs) + list(arguments.args)
    positional_defaults = [None] * (len(positional) - len(arguments.defaults)) + list(arguments.defaults)
    parameters: List[Dict[str, Any]] = []

    for argument, default in zip(positional, positional_defaults):
        parameters.append(
            {
                "name": argument.arg,
                "kind": "positional",
                "annotation": _annotation(source, argument.annotation),
                "hasDefault": default is not None,
            }
        )

    if arguments.vararg is not None:
        parameters.append(
            {
                "name": arguments.vararg.arg,
                "kind": "var-positional",
                "annotation": _annotation(source, arguments.vararg.annotation),
                "hasDefault": False,
            }
        )

    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        parameters.append(
            {
                "name": argument.arg,
                "kind": "keyword-only",
                "annotation": _annotation(source, argument.annotation),
                "hasDefault": default is not None,
            }
        )

    if arguments.kwarg is not None:
        parameters.append(
            {
                "name": arguments.kwarg.arg,
                "kind": "var-keyword",
                "annotation": _annotation(source, arguments.kwarg.annotation),
                "hasDefault": False,
            }
        )

    return parameters


def _route_methods(decorator_name: str, decorator: ast.Call) -> List[str]:
    if decorator_name != "api_route":
        return [decorator_name.upper()]
    for keyword in decorator.keywords:
        if keyword.arg == "methods":
            methods = _literal_or_dynamic(keyword.value)
            if isinstance(methods, (list, tuple)) and all(isinstance(method, str) for method in methods):
                return sorted({method.upper() for method in methods})
            return ["<DYNAMIC>"]
    return ["<UNSPECIFIED>"]


def _route_path(decorator: ast.Call) -> Any:
    if decorator.args:
        return _literal_or_dynamic(decorator.args[0])
    for keyword in decorator.keywords:
        if keyword.arg == "path":
            return _literal_or_dynamic(keyword.value)
    return "<dynamic>"


def _decorator_options(decorator: ast.Call) -> Dict[str, Any]:
    return {
        keyword.arg: _literal_or_dynamic(keyword.value)
        for keyword in decorator.keywords
        if keyword.arg != "methods" and keyword.arg is not None
    }


def _signature_hash(signature: Dict[str, Any]) -> str:
    canonical = json.dumps(signature, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scan_tree(tree: ast.AST, source: str, relative_path: str) -> List[Dict[str, Any]]:
    functions: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            parsed = _decorator_call(decorator)
            if parsed is None:
                continue
            decorator_name, decorator_call = parsed
            methods = _route_methods(decorator_name, decorator_call)
            route_path = _route_path(decorator_call)
            parameters = _function_parameters(source, node)
            signature = {
                "handler": node.name,
                "methods": methods,
                "path": route_path,
                "parameters": parameters,
                "returnAnnotation": _annotation(source, node.returns),
                "isAsync": isinstance(node, ast.AsyncFunctionDef),
            }
            functions.append(
                {
                    "layer": "MW",
                    "name": node.name,
                    "file": relative_path,
                    "line": node.lineno,
                    "methods": methods,
                    "path": route_path,
                    "parameters": parameters,
                    "returnAnnotation": signature["returnAnnotation"],
                    "isAsync": signature["isAsync"],
                    "options": _decorator_options(decorator_call),
                    "signatureHash": _signature_hash(signature),
                }
            )
    return functions


def _python_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        if not any(part in EXCLUDED_DIRECTORIES for part in path.parts):
            yield path


def scan(root: Path) -> Dict[str, Any]:
    functions: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    for path in _python_files(root):
        relative_path = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative_path)
        except (OSError, SyntaxError) as error:
            diagnostics.append(
                {
                    "file": relative_path,
                    "error": type(error).__name__,
                    "message": str(error),
                }
            )
            continue
        functions.extend(_scan_tree(tree, source, relative_path))

    functions.sort(key=lambda item: (item["file"], item["line"], item["name"], item["methods"]))
    diagnostics.sort(key=lambda item: item["file"])
    return {"component": "MW", "functions": functions, "diagnostics": diagnostics}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", type=Path, help="Directory to scan")
    args = parser.parse_args(argv)
    result = scan(args.root.resolve())
    json.dump(result, sys.stdout, ensure_ascii=True, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if not result["diagnostics"] else 1


if __name__ == "__main__":
    raise SystemExit(main())