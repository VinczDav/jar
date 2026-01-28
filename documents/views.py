from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from .models import Document, DocumentCategory, DocumentVersion


@login_required
def document_list(request):
    """Show documents by category."""
    categories = DocumentCategory.objects.all()
    selected_category = request.GET.get('category', '')

    # Get documents
    documents = Document.objects.filter(is_active=True)
    if selected_category:
        documents = documents.filter(category_id=selected_category)

    # Search
    search = request.GET.get('search', '')
    if search:
        documents = documents.filter(title__icontains=search)

    documents = documents.select_related('category').prefetch_related('versions')

    context = {
        'categories': categories,
        'documents': documents,
        'selected_category': selected_category,
        'search': search,
        'can_upload': request.user.is_jt_admin,
    }
    return render(request, 'documents/list.html', context)


@login_required
def document_upload(request):
    """JT Admin: Upload a new document."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    categories = DocumentCategory.objects.all()

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        category_id = request.POST.get('category', '')
        version_number = request.POST.get('version_number', '1.0').strip()

        if not title:
            return render(request, 'documents/upload.html', {
                'error': 'A cím megadása kötelező.',
                'categories': categories,
            })

        if 'file' not in request.FILES:
            return render(request, 'documents/upload.html', {
                'error': 'Fájl feltöltése kötelező.',
                'categories': categories,
            })

        # Create document
        document = Document(
            title=title,
            description=description,
        )
        if category_id:
            document.category_id = category_id
        document.save()

        # Create first version
        DocumentVersion.objects.create(
            document=document,
            version_number=version_number,
            file=request.FILES['file'],
            uploaded_by=request.user,
        )

        return redirect('documents:list')

    return render(request, 'documents/upload.html', {'categories': categories})


@login_required
def document_new_version(request, document_id):
    """JT Admin: Upload a new version of a document."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    document = get_object_or_404(Document, id=document_id)

    if request.method == 'POST':
        version_number = request.POST.get('version_number', '').strip()
        changelog = request.POST.get('changelog', '').strip()

        if not version_number:
            return render(request, 'documents/new_version.html', {
                'error': 'A verziószám megadása kötelező.',
                'document': document,
            })

        if 'file' not in request.FILES:
            return render(request, 'documents/new_version.html', {
                'error': 'Fájl feltöltése kötelező.',
                'document': document,
            })

        # Check if version already exists
        if document.versions.filter(version_number=version_number).exists():
            return render(request, 'documents/new_version.html', {
                'error': 'Ez a verziószám már létezik.',
                'document': document,
            })

        # Create new version
        DocumentVersion.objects.create(
            document=document,
            version_number=version_number,
            file=request.FILES['file'],
            changelog=changelog,
            uploaded_by=request.user,
        )

        return redirect('documents:list')

    return render(request, 'documents/new_version.html', {'document': document})


@login_required
def api_document_delete(request, document_id):
    """JT Admin: Delete (deactivate) a document."""
    if not request.user.is_jt_admin:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        document = Document.objects.get(id=document_id)
        document.is_active = False
        document.save()
        return JsonResponse({'success': True})
    except Document.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
