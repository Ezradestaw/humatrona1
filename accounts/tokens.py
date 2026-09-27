from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """
    Generate single-use, time-limited cryptographic tokens for email verification.
    """
    def _make_hash_value(self, user, timestamp):
        # Invalidate the token once the user's email is verified or password changes
        return f"{user.pk}{timestamp}{user.is_email_verified}{user.password}"


email_verification_token = EmailVerificationTokenGenerator()
