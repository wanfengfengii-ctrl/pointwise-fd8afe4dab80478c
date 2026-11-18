def validate_threshold(threshold):
    if type(threshold) is not int:
        raise ValueError('threshold must be an integer sample count')


def meets_threshold(sample, threshold):
    return sample >= threshold
