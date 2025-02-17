from django import forms
from .models import Organization, OrganizationMember

class OrganizationForm(forms.ModelForm):
    """Form for creating and updating organizations."""
    
    class Meta:
        model = Organization
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input w-full px-4 py-2 rounded-lg',
                'placeholder': 'Organization Name'
            })
        }

class MemberInviteForm(forms.Form):
    """Form for inviting new members to an organization."""
    
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-input w-full px-4 py-2 rounded-lg',
            'placeholder': 'member@example.com'
        })
    )
    
    role = forms.ChoiceField(
        choices=OrganizationMember.ROLE_CHOICES,
        initial='MEMBER',
        widget=forms.Select(attrs={
            'class': 'form-input w-full px-4 py-2 rounded-lg'
        })
    )

class MemberRoleForm(forms.Form):
    """Form for changing a member's role."""
    
    role = forms.ChoiceField(
        choices=OrganizationMember.ROLE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-input w-full px-4 py-2 rounded-lg'
        })
    )
    
    member_id = forms.IntegerField(widget=forms.HiddenInput()) 