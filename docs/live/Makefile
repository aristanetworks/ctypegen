CFLAGS += -g -fPIC
all: testme testmegen.py libcgen.py
libtestme.so: testme.o
	$(CC) -shared -g -o $@ $^

testme: main.o libtestme.so
	$(CC) -o $@ $^ -Wl,-rpath=.

testmegen.py: libtestme.so ctype.py
	python ./ctype.py

libcgen.py: testmegen.py

clean:
	rm -fr libtestme.so *o *gen.py *pyc __pycache__ a.out testme
