def restore_even(low, previous_high, current_high):
    return low - (previous_high + current_high + 2) // 4


def restore_odd(high, preceding_even, following_even):
    return high + (preceding_even + following_even) // 2
