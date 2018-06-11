#include <stdlib.h>
#include <stdio.h>

int functionToTest()
{
    int sum = 0;
    char buf[1024];
    for (;;) {
        puts("enter a number (ctrl-d to finish): ");
        char *p = fgets(buf, sizeof buf, stdin);
        if (p == 0)
            break;
        int val = atoi(p);
        sum += val;
    }
    return sum;
}
