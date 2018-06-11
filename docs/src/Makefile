.PHONY: clean check all

.SUFFIXES: .htmlc .htmlpy .py

all: htmlfilt check basic.htmlc libcallback.so callbackgen.py callback.htmlpy callback.htmlc
	python ./dirtybasic.py > basic.out
	objdump --dwarf=info libbasic.so | ./htmlfilt > basic-objdump.out

CFLAGS += -fPIC -g

libbasic.so: basic.o
	$(CC) -shared -o $@ $^

libcallback.so: callback.o
	$(CC) -shared -o $@ $^

callbackgen.py: libcallback.so callbackg.py
	./callbackg.py

basic.py: libbasic.so
	python ./generate.py
clean:
	rm -f *.o *.pyc basic-objdump.out basic.out basic.py *.so *gen.py htmlfilt *htmlc *htmlpy

check: basic.py
	python ./basic.py

.c.htmlc: htmlfilt
	./htmlfilt < $< > $@

.py.htmlpy: htmlfilt
	./htmlfilt < $< > $@

htmlfilt: htmlfilt.c
	$(CC) -o $@ $^
