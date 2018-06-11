typedef int (*Callback)(int a, int b);

int callme(int a, int b, Callback action)
{
    return action(a, b);
}

