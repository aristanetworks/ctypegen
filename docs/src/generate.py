from  CTypeGen import generate, PythonType

generate(["libbasic.so"], "basic.py", [PythonType("SomeStructure")], ["someFunction"])
