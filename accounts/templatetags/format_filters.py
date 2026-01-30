from django import template

register = template.Library()


@register.filter
def hu_number(value):
    """
    Format a number with Hungarian thousands separator (space).
    Example: 15000 -> "15 000"
    """
    try:
        # Convert to integer if it's a float/decimal
        num = int(value)
        # Format with commas then replace with spaces
        formatted = f"{num:,}".replace(',', ' ')
        return formatted
    except (ValueError, TypeError):
        return value
