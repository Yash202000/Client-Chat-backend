def run(params, config):
    """
    Calculates the sum of two numbers, converting inputs to numbers if possible.
    Stores the result directly into the 'result' key of the exec_globals.
    """

    try:
        num1 = float(params.get('num1'))
        num2 = float(params.get('num2'))
        
        return num1 + num2
    except (ValueError, TypeError):
        return "Error: Could not convert 'num1' and 'num2' to numbers."
