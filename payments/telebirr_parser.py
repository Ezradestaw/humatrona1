import re
import hashlib
from decimal import Decimal, InvalidOperation


class TelebirrMessageParser:
    """
    Parser for Telebirr SMS and transaction confirmation messages (Section 28).
    Treats input strictly as untrusted text.
    Extracts transaction reference, amount, currency, and timestamps.
    """

    RESERVED_WORDS = {
        'TRANSFERRED', 'SUCCESSFUL', 'CUSTOMER', 'NOTIFICATION',
        'CONFIRMATION', 'TELEBIRR', 'TRANSFER', 'BALANCE', 'ACCOUNT',
        'ETHIOTELECOM', 'ETHIOPIA', 'HUMATRON', 'COMPLETED'
    }

    # Explicit prefixed patterns (highest priority)
    PREFIXED_PATTERNS = [
        r'(?:transaction\s*(?:(?:no\.?|number|id|ref|reference)\s*(?:is|:)?|[:#])\s*)([A-Za-z0-9_\-]{6,32})\b',
        r'(?:የግብይት\s*ቁጥር(?:ዎ)?[:\s]+)([A-Za-z0-9_\-]{6,32})\b',
    ]

    # Standalone code pattern (must have both digits and letters)
    STANDALONE_PATTERN = r'\b([A-Z0-9]{8,18})\b'

    # Amount extraction patterns for ETB / ብር
    AMOUNT_PATTERNS = [
        r'(?:ETB|ብር|birr)\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)',
        r'([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)\s*(?:ETB|ብር|birr)',
        r'(?:amount|ክፍያ)[:\s]+([0-9]+(?:\.[0-9]{1,2})?)',
    ]

    # Date/time patterns
    DATE_PATTERNS = [
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)',
        r'(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})',
    ]

    # Phone/account numbers
    PHONE_PATTERNS = [
        r'\b(09\d{8}|07\d{8}|\+2519\d{8}|\+2517\d{8})\b',
    ]

    @classmethod
    def parse(cls, raw_text):
        """
        Parses raw text message into a structured dictionary.
        Returns dict with:
            is_valid: bool
            transaction_id: str or None
            amount: Decimal or None
            currency: 'ETB'
            date_str: str or None
            phone_found: str or None
            message_hash: str
            errors: list[str]
        """
        raw_text_clean = (raw_text or '').strip()
        message_hash = hashlib.sha256(raw_text_clean.encode('utf-8')).hexdigest()
        errors = []

        if len(raw_text_clean) < 15:
            return {
                'is_valid': False,
                'transaction_id': None,
                'amount': None,
                'currency': 'ETB',
                'date_str': None,
                'phone_found': None,
                'message_hash': message_hash,
                'errors': ['Message text is too short to be a valid Telebirr notification.'],
            }

        # 1. Extract transaction ID
        transaction_id = None
        
        # Check prefixed patterns first
        for pattern in cls.PREFIXED_PATTERNS:
            match = re.search(pattern, raw_text_clean, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip().upper()
                if candidate not in cls.RESERVED_WORDS and len(candidate) >= 6:
                    transaction_id = candidate
                    break

        # Fallback to standalone codes only if prefixed not found
        if not transaction_id:
            for match in re.finditer(cls.STANDALONE_PATTERN, raw_text_clean):
                candidate = match.group(1).strip().upper()
                # Must not be a reserved word, must contain at least one digit and one letter
                if (candidate not in cls.RESERVED_WORDS and 
                    any(c.isdigit() for c in candidate) and 
                    any(c.isalpha() for c in candidate)):
                    transaction_id = candidate
                    break

        if not transaction_id:
            errors.append('Could not extract a valid Telebirr transaction ID.')

        # 2. Extract Amount
        amount = None
        for pattern in cls.AMOUNT_PATTERNS:
            match = re.search(pattern, raw_text_clean, re.IGNORECASE)
            if match:
                raw_amt = match.group(1).replace(',', '')
                try:
                    amount = Decimal(raw_amt)
                    if amount > 0:
                        break
                except (InvalidOperation, ValueError):
                    continue

        if not amount:
            errors.append('Could not extract a valid ETB payment amount.')

        # 3. Extract Date/Time (optional)
        date_str = None
        for pattern in cls.DATE_PATTERNS:
            match = re.search(pattern, raw_text_clean)
            if match:
                date_str = match.group(1)
                break

        # 4. Extract Phone (optional)
        phone_found = None
        phone_match = re.search(cls.PHONE_PATTERNS[0], raw_text_clean)
        if phone_match:
            phone_found = phone_match.group(1)

        is_valid = (transaction_id is not None) and (amount is not None)

        return {
            'is_valid': is_valid,
            'transaction_id': transaction_id,
            'amount': amount,
            'currency': 'ETB',
            'date_str': date_str,
            'phone_found': phone_found,
            'message_hash': message_hash,
            'errors': errors,
        }
