import os
import sys
from setuptools import setup
from setuptools.command.build_ext import build_ext


class OptionalBuildExt(build_ext):
    """
    Builds the native C++20 core extension if a C++ compiler is available,
    falling back gracefully to pure Python when native compilation fails.
    """

    def build_extension(self, ext):
        try:
            super().build_extension(ext)
        except Exception as e:
            print(f"\n[!] Warning: Failed to build native C++ core ({e}).")
            print("[+] ZERENE will continue running in pure Python mode.\n")


ext_modules = []

try:
    from pybind11.setup_helpers import Pybind11Extension

    cpp_source = os.path.join("src", "zerene_core", "bindings.cpp")
    if os.path.exists(cpp_source):
        extra_compile_args = []
        extra_link_args = []

        if sys.platform == "win32":
            cc = os.environ.get("CC", "").lower()
            if "gcc" in cc or "clang" in cc:
                extra_compile_args = ["-O3", "-std=c++20"]
                extra_link_args = ["-static", "-static-libgcc", "-static-libstdc++"]
            else:
                extra_compile_args = ["/O2", "/std:c++20"]
        elif sys.platform == "darwin":
            extra_compile_args = ["-O3", "-std=c++20", "-stdlib=libc++"]
        else:
            extra_compile_args = ["-O3", "-std=c++20"]

        if sys.platform != "darwin" and os.environ.get(
            "ZERENE_NATIVE_ARCH", ""
        ).lower() in ("1", "true"):
            if sys.platform != "win32" or (
                "gcc" in os.environ.get("CC", "").lower()
                or "clang" in os.environ.get("CC", "").lower()
            ):
                extra_compile_args.append("-march=native")

        ext_modules = [
            Pybind11Extension(
                "zerene.zerene_cpp_core",
                [cpp_source],
                include_dirs=[os.path.join("src", "zerene_core")],
                cxx_std=20,
                extra_compile_args=extra_compile_args,
                extra_link_args=extra_link_args,
            )
        ]
except ImportError:
    pass

setup(
    ext_modules=ext_modules,
    cmdclass={"build_ext": OptionalBuildExt} if ext_modules else {},
)
