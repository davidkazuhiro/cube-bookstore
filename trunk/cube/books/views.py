# django imports
from cube.books.models import Book, Listing
from cube.books.view_tools import listing_filter, listing_sort, get_number
from cube.books.email import send_missing_emails, send_sold_emails,\
                             send_tbd_emails
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator, InvalidPage, EmptyPage
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import render_to_response
from django.template import RequestContext

#python imports
from datetime import datetime
from decimal import Decimal

# pagination defaults
PER_PAGE = '30'
PER_PAGE_STAFF = '20'
PAGE_NUM = '1'

@login_required()
def listings(request):
    """
    Shows a list of all the books listed.
    Does pagination, sorting and filtering.
    """
    # Filter for the search box
    if request.GET.has_key("filter") and request.GET.has_key("field"):
        # only run the filter if the GET args are there
        listings = listing_filter(request.GET["filter"] , request.GET["field"],
                                  Listing.objects.all())
    elif request.GET.has_key("sort_by") and request.GET.has_key("dir"):
        listings = listing_sort(request.GET["sort_by"], request.GET["dir"])
    else:
        listings = Listing.objects.all()

    # Filter according to permissions
    if not request.user.is_staff:
        # Non staff can only see listings which are for sale.
        listings = filter(lambda x: x.status == 'F', listings)

    # Pagination
    page_num = get_number(request.GET, 'page', PAGE_NUM)
    listings_per_page = get_number(request.GET, 'per_page', PER_PAGE)

    paginator = Paginator(listings, listings_per_page)
    try:
        page_of_listings = paginator.page(page_num)
    except (EmptyPage, InvalidPage):
        page_of_listings = paginator.page(paginator.num_pages)

    # Template time
    vars = {
        'listings' : page_of_listings,
        'per_page' : listings_per_page,
        'page' : page_num,
        'field' : request.GET.get('field', 'any_field'),
        'filter_text' : request.GET.get('filter', ''),
        'dir' : 'desc' if request.GET.get('dir', '') == 'asc' else 'asc'
    }
    return render_to_response('books/listing_list.html', vars, 
                              context_instance=RequestContext(request))
@login_required()
def update_data(request):
    """
    This view is used to update book data
    """
    def singlural(number):
        """
        Returns appropriate text depending on the singularity of the number
        """
        if number == 1: return "1 item has been"
        return "%s items have been" % number

    def set_bunch(attr, value):
        """
        Sets a status on all listings given and saves them
        """
        for listing in bunch:
            setattr(listing, attr, value)
            listing.save()

    messages = []
    bunch = Listing.objects.none()
    action = request.POST.get("Action", '')
    singular = "item has been"
    plural = "items have been"

    for key, value in request.POST.items():
        if "idToEdit" in key:
            bunch = bunch | Listing.objects.filter(pk=int(value))
            
    if action == "Delete":
        set_bunch('status', 'D')
        messages.append("%s deleted." % singlural(len(bunch)))
    elif action[:1] == "To Be Deleted"[:1]:
        # apparently some browsers have issues passing spaces
        # TODO add bells and whistles
        # can't do this for Deleted, Seller Paid, and Sold Books
        bunch = bunch.exclude(status__in='DPS')
        send_tbd_emails(bunch)
        vars = {
            'num_doomed' : bunch.count(),
            'num_owners' : len(set(map(lambda x: x.seller, bunch))),
        }
        bunch.update(status='T')
        return render_to_response('books/update_data/to_be_deleted.html', vars,
                                  context_instance=RequestContext(request))
    elif action == "Sold":
        # Allow only if For Sale or On Hold
        bunch = bunch.filter(status__in='FO')
        send_sold_emails(list(bunch))
        vars = {
            'sold' : len(bunch),
            'num_owners' : len(set(map(lambda x: x.seller, bunch))),
        }
        bunch.update(status='S', sell_date=datetime.today())
        return render_to_response('books/update_data/sold.html', vars, 
                                  context_instance=RequestContext(request))
    elif action[:5] == "Seller Paid"[:5]:
        # apparently some browsers have issues passing spaces

        # only staff can do this
        if not request.user.is_staff: bunch = Listing.objects.none()
        # A Seller can be paid only after the book was sold
        else: bunch = bunch.filter(status='S')

        vars = {'paid' : len(bunch)}
        bunch.update(status='P')
        return render_to_response('books/update_data/seller_paid.html', vars, 
                                  context_instance=RequestContext(request))
    elif action == "Missing":
        # Must be For Sale, On Hold or To Be Deleted for it to go Missing
        bunch = bunch.filter(status__in='FOT')
        send_missing_emails(bunch)
        vars = {
            'num_owners' : len(set(map(lambda x: x.seller, bunch))),
            'num_missing' : len(bunch),
        }
        bunch.update(status='M')
        return render_to_response('books/update_data/missing.html', vars, 
                                  context_instance=RequestContext(request))
    elif action[:4] == "Place on Hold"[:4]:
        # apparently some browsers have issues passing spaces
        extended = bunch.filter(status='O', holder=request.user)
        new_hold = bunch.filter(status='F')
        failed = bunch.exclude(status__in='OF', holder=request.user)
        held = extended | new_hold
        vars = {
            'failed' : failed,
            'extended' : extended,
            'new_hold' : new_hold,
            'num_held' : held.count(),
            'total_price' : sum(map(lambda x: x.price, held)),
        }
        extended.update(hold_date = datetime.today())
        new_hold.update(status='O', hold_date=datetime.today(), holder=request.user)
        return render_to_response('books/update_data/place_hold.html', vars, 
                                  context_instance=RequestContext(request))
    elif action[:5] == "Remove Holds"[:5]:
        bunch = bunch.filter(status='O')
        if not request.user.is_staff: bunch = bunch.filter(holder=request.user)
        vars = {'removed' : len(bunch)}
        bunch.update(status='F', hold_date=None, holder=None)
        return render_to_response('books/update_data/remove_holds.html', vars,
                                  context_instance=RequestContext(request))
    elif action == "Edit":
        too_many = True if bunch.count() > 1 else False
        item = bunch[0]
        rows = [{'name' : 'Bar Code', 'value' : item.book.barcode},
                {'name' : 'Student ID', 'value' : item.seller.id},
                {'name' : 'Price', 'value' : item.price},
                {'name' : 'Buyer Student ID', 'value' : item.holder.id}]
        vars = {
            'rows' : rows,
            'too_many' : too_many,
            'id' : item.id,
        }
        return render_to_response('books/update_data/edit.html', vars, 
                                  context_instance=RequestContext(request))
    else:
        vars = {'action' : action}
        return render_to_response('books/update_data/error.html', vars, 
                                  context_instance=RequestContext(request))
@login_required()
def update_listing(request):
    """
    Applies changes to a listing.
    If the barcode doesn't exist,
    it makes the user create a Book object as well
    """
    if request.POST.has_key('IdToEdit'):
        listing = Listing.objects.get(id=int(request.POST["IdToEdit"]))
        g = request.POST.get
        if g('bar-code', ''):
            # there is a barcode
            barcode = g('bar-code', '')
            return HttpResponse("There is a barcode")
            if Book.objects.filter(barcode=barcode):
                # a book exists in the db with that barcode
                return HttpResponse("A Book exists with that barcode")
                listing.book =  Book.objects.get(barcode=barcode)
            else:
                # barcode doesn't exist in db, we have to make a book.
                return HttpResponse("barcode doesn't exist in db, we have to make a book")
        return HttpResponse('<p>Edit</p>')
        # TODO finish this
        listing.book = Book.objects.get(barcode=g('bar-code', listing.book.barcode))
        listing.seller = User.objects.get(id=int(g('student-id', str(listing.seller.id))))
        listing.price = Decimal(g('price', str(listing.price)))
        listing.holder = User.objects.get(id=int(g('buyer-student-id', str(listing.holder.id))))
    else:
        return HttpResponse('<p>Bad</p>')

@login_required()
def myBooksies(request):
    """
    Displays books the user has on hold
    and is selling, sorts by search box, filters, calculates total prices
  
    """
    #gets users books
    selling = Listing.objects.filter(seller = request.user)  
    holding = Listing.objects.filter(holder = request.user)    
    priceHold = 0
    priceSell = 0
    searched = False
    #calculate totals for book
    for listing in holding:
        priceHold = listing.price + priceHold         
    for listing in selling:
        priceSell = listing.price + priceSell
    
  
    # Filter for the search box
    if request.GET.has_key("filter") and request.GET.has_key("field"):
        # only run the filter if the GET args are there
        selling = listing_filter(request.GET["filter"] , request.GET["field"],
                                  selling)
        holding = listing_filter(request.GET["filter"] , request.GET["field"],
                                  holding)
        searched = True
    # Sorts results by request
    elif request.GET.has_key("sort_by") and request.GET.has_key("dir"):
        holding = listing_sort(request.GET["sort_by"], request.GET["dir"])
        holding = holding.filter(holder = request.user)
    elif request.GET.has_key("sort_with") and request.GET.has_key("dir"):
        selling = listing_sort(request.GET["sort_with"], request.GET["dir"])
        selling = selling.filter(seller = request.user)
   
    vars = {
         'sellP' : selling,
         'holdP' : holding,
         'priceH' : priceHold,
         'priceS' : priceSell,
         'field' : request.GET.get('field', 'any_field'),
         'filter_text' : request.GET.get('filter', ''),
         'search' : searched
    }             
    return render_to_response('myBooks.html', vars,
                              context_instance=RequestContext(request))    
    
@login_required()    
def staff(request):
    listings = User.objects.filter(is_staff = True)
    page_num = get_number(request.GET, 'page', PAGE_NUM)
    listings_per_page = get_number(request.GET, 'per_page', PER_PAGE)
    paginator = Paginator(listings, listings_per_page)
    try:
        page_of_listings = paginator.page(page_num)
    except (EmptyPage, InvalidPage):
        page_of_listings = paginator.page(paginator.num_pages)
    vars = {
        'listings' : page_of_listings,
        'per_page' : listings_per_page,
        'page' : page_num,
        'field' : request.GET.get('field', 'any_field'),
        'filter_text' : request.GET.get('filter', ''),
        'dir' : 'desc' if request.GET.get('dir', '') == 'asc' else 'asc'
    }
    return render_to_response('books/staff.html', vars, 
    context_instance=RequestContext(request))

@login_required()
def staffedit(request):
    messages = []; 
    first_name = "";
    last_name = "";
    student_id = "";
    if request.user.is_authenticated():
        student_id = request.POST.get("student_id", '')
        #user is selected
        if request.POST.get("Action", ''):
            messages.append(request.POST.get("Action", ''))
            listings = User.objects.get(username = messages[0])    
            student_id = listings.id
            first_name = listings.first_name
            last_name = listings.last_name

        #Delete User
        if (request.POST.get("Delete", '')):
            if student_id:
                try:
                    listings = User.objects.get(id = student_id)
                    listings.is_superuser = False
                    listings.is_staff = False
                    listings.save()
                    return HttpResponse("User Deleted")
                except User.DoesNotExist:
                    return HttpResponse("User does not Exist")

            if len(messages) > 0:
                try:
                    listings = User.objects.get(id = messages[1])  
                    listings.is_superuser = False
                    listings.is_staff = False
                    listings.save()
                    return HttpResponse("User Deleted")
                except listings.DoesNotExist:
                    return HttpResponse("User does not Exist")

        #Save New User
        if (request.POST.get("Save", '')):
            role = request.POST.get("role", '')
            try:
                listings = User.objects.get(id = student_id)
                if request.POST.get("role", '') == "Administrator":
                    listings.is_superuser = True
                    listings.is_staff = True
                    listings.save()
                else:
                    listings.is_superuser = False
                    listings.is_staff = True
                    listings.save()
                
            except:
                return HttpResponse("Invalid Student ID")
                 
    vars = {
       'messages' : messages,
       'first_name' : first_name,
       'last_name' : last_name,
       'student_id' : student_id
    }
    return render_to_response('books/staffedit.html', vars, 
    context_instance=RequestContext(request))


def addBooks(request):
    if request.POST.get("AltDBld") and request.POST.get("Price") and request.POST.get("BarCode"):
        correct_BarCode = request.POST.get("BarCode")
        studentID = int(request.POST.get("AltDBld"))
        dec_price = Decimal(request.POST.get("Price"))
        try:
            booky = Book.objects.get(barcode=correct_BarCode)
        except Book.DoesNotExist: 
            return render_to_response('newBook.html', context_instance=RequestContext(request))
        try:
            selly = User.objects.get(id = studentID)
        except User.DoesNotExist:
            return HttpResponse("User does not exist")
        newListing = Listing(list_date=datetime.now(), price=dec_price, status="F", book=booky, seller = selly)
        newListing.save()
        return HttpResponse("work")
    if request.POST.get("Author"):
# and request.POST.get("Title") and request.POST.get("Edition") and request.POST.get("Department") and request.POST.get("Course Number"):
        course = request.POST.get("Department") + " " + request.POST.get("Course Number")
        the_author = request.POST.get("Author")
        the_title = request.POST.get("Title")
        the_edition = request.POST.get("Edition")
        new_book = Book(author = the_author, title = the_title, edition = the_edition, courses = course) 
        new_book.save()
        return HttpResponse("happy")
    else:
        return render_to_response('addBooks.html', context_instance=RequestContext(request))

def listBooks(request):
    if request.GET.has_key("sort_by") and request.GET.has_key("dir"):
        books = listing_sort(request.GET["sort_by"], request.GET["dir"])
    else:
        books = Book.objects.all()

    # Filter according to permissions
    if not request.user.is_staff:
        # Non staff can only see listings which are for sale.
        books = filter(lambda x: x.status == 'F', books)

    # Pagination
    page_num = get_number(request.GET, 'page', PAGE_NUM)
    books_per_page = get_number(request.GET, 'per_page', PER_PAGE)

    paginator = Paginator(books, books_per_page)
    try:
        page_of_listings = paginator.page(page_num)
    except (EmptyPage, InvalidPage):
        page_of_listings = paginator.page(paginator.num_pages)

    # Template time
    vars = {
        'listings' : page_of_listings,
        'per_page' : books_per_page,
        'page' : page_num,
        'dir' : 'desc' if request.GET.get('dir', '') == 'asc' else 'asc'
    }

    return render_to_response('books/listBooks.html', vars, context_instance=RequestContext(request))
