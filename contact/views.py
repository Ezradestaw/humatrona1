from django.contrib import messages
from django.shortcuts import render, redirect
from .forms import ContactForm
from notifications.services import EmailService


def contact_view(request):
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            contact_msg = form.save(commit=False)
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                contact_msg.ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                contact_msg.ip_address = request.META.get('REMOTE_ADDR')
            contact_msg.save()

            # Dispatch notification to administrator
            EmailService.send_admin_contact_notification(contact_msg)

            messages.success(request, "Your message has been received. Our team will review and respond shortly.")
            return redirect('contact:index')
    else:
        initial = {}
        if request.user.is_authenticated:
            initial = {
                'name': request.user.full_name,
                'email': request.user.email,
            }
        form = ContactForm(initial=initial)

    return render(request, 'contact/contact.html', {'form': form})
