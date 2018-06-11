#include <stdio.h>
extern int functionToTest(void);

int main()
{
    printf("%d\n", functionToTest());
}

