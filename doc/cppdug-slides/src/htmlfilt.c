#include <stdio.h>
int
main()
{
    int c;
    while ((c = getc(stdin)) != EOF) {
        switch (c) {
            case '<': printf("&lt;"); break;
            case '>': printf("&gt;"); break;
            case '"': printf("&quot;"); break;
            case '&': printf("&amp;"); break;
            case '\'': printf("&apos;"); break;
            default: putc(c,stdout); break;
        }
    }
    return 0;
}
