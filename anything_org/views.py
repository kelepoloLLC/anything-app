from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .models import Organization, OrganizationMember
from .forms import OrganizationForm

@login_required
def organization_list(request):
    """View to list user's organizations."""
    user_organizations = request.user.organizations.all()
    owned_organizations = request.user.owned_organizations.all()
    
    return render(request, 'organizations/list.html', {
        'user_organizations': user_organizations,
        'owned_organizations': owned_organizations
    })

@login_required
def organization_create(request):
    """View to create a new organization."""
    if request.method == 'POST':
        form = OrganizationForm(request.POST)
        if form.is_valid():
            organization = form.save(commit=False)
            organization.owner = request.user
            organization.save()
            
            # Add owner as admin member
            OrganizationMember.objects.create(
                organization=organization,
                user=request.user,
                role='ADMIN'
            )
            
            messages.success(request, 'Organization created successfully!')
            return redirect('organization_detail', org_id=organization.id)
    else:
        form = OrganizationForm()
    
    return render(request, 'organizations/create.html', {'form': form})

@login_required
def organization_detail(request, org_id):
    """View to show organization details."""
    organization = get_object_or_404(Organization, id=org_id)
    user_member = organization.organizationmember_set.filter(user=request.user).first()
    
    if not user_member:
        messages.error(request, 'You do not have access to this organization.')
        return redirect('organization_list')
    
    members = organization.organizationmember_set.select_related('user').all()
    
    return render(request, 'organizations/detail.html', {
        'organization': organization,
        'members': members,
        'user_role': user_member.role
    })

@login_required
def organization_update(request, org_id):
    """View to update organization details."""
    organization = get_object_or_404(Organization, id=org_id)
    
    if organization.owner != request.user:
        messages.error(request, 'Only the organization owner can update details.')
        return redirect('organization_detail', org_id=org_id)
    
    if request.method == 'POST':
        form = OrganizationForm(request.POST, instance=organization)
        if form.is_valid():
            form.save()
            messages.success(request, 'Organization updated successfully!')
            return redirect('organization_detail', org_id=org_id)
    else:
        form = OrganizationForm(instance=organization)
    
    return render(request, 'organizations/update.html', {
        'form': form,
        'organization': organization
    })

@login_required
def member_manage(request, org_id):
    """View to manage organization members."""
    organization = get_object_or_404(Organization, id=org_id)
    user_member = organization.organizationmember_set.filter(user=request.user).first()
    
    if not user_member or user_member.role not in ['ADMIN', 'OWNER']:
        messages.error(request, 'You do not have permission to manage members.')
        return redirect('organization_detail', org_id=org_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        member_id = request.POST.get('member_id')
        
        if action and member_id:
            member = get_object_or_404(OrganizationMember, id=member_id)
            
            if action == 'remove':
                member.delete()
                messages.success(request, 'Member removed successfully!')
            elif action == 'change_role':
                new_role = request.POST.get('role')
                if new_role in ['ADMIN', 'MEMBER', 'VIEWER']:
                    member.role = new_role
                    member.save()
                    messages.success(request, 'Member role updated successfully!')
        
        return redirect('member_manage', org_id=org_id)
    
    members = organization.organizationmember_set.select_related('user').all()
    return render(request, 'organizations/members.html', {
        'organization': organization,
        'members': members,
        'user_role': user_member.role
    })

@login_required
def member_invite(request, org_id):
    """View to invite new members to the organization."""
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        organization = get_object_or_404(Organization, id=org_id)
        user_member = organization.organizationmember_set.filter(user=request.user).first()
        
        if not user_member or user_member.role not in ['ADMIN', 'OWNER']:
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        email = request.POST.get('email')
        role = request.POST.get('role', 'MEMBER')
        
        # Here you would typically send an invitation email
        # For MVP, we'll just return success
        return JsonResponse({
            'success': True,
            'message': f'Invitation sent to {email}'
        })
    
    return JsonResponse({'error': 'Invalid request'}, status=400)
