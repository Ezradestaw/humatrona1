from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """
    Generate single-use, time-limited cryptographic tokens for email verification.
    """
    def _make_hash_value(self, user, timestamp):
        # Invalidate the token once the user's email is verified or password changes
        return f"{user.pk}{timestamp}{user.is_email_verified}{user.password}"


email_verification_token = EmailVerificationTokenGenerator()


class EducationalEmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """
    Section 10: Single-use, time-limited cryptographic tokens for educational email verification.
    """
    def _make_hash_value(self, user, timestamp):
        sv = getattr(user, 'student_verification', None)
        edu_email = sv.educational_email if sv else ''
        edu_verified = sv.educational_email_verified if sv else False
        return f"{user.pk}{timestamp}{edu_email}{edu_verified}{user.password}"


educational_email_token = EducationalEmailVerificationTokenGenerator()

