(function(){
'use strict';

angular.module('auth_request', [
  'auth_circu',
  'ui.select',
  'ngSanitize'
])

.controller('RequestFormCtrl', function () {

  /* For Salèse, limit to 01/05 to 30/11 */

  var vm = this;


  vm.places = window.PRELOAD_PLACES;

  vm.request = {
    date: new Date(),
    motive: '0ecf0057-9a31-41d4-8624-5bd1d1702128',
    docs: [],
    author: {
      name: undefined,
      prefix: 'n/a',
      address: undefined,
      phone: undefined
    },
    authorization: {
      prescriptions: undefined,
      places: [],
      vehicules: [],
      startDate: undefined,
      endDate: undefined
    },
    groupVehicules: false
  }

  // TODO: check that dates are not contradictoring

  vm.addDoc = function(e){
    e.preventDefault();
    vm.request.docs.push({
      type: "proofOfAddress",
      date: new Date(),
    });
  }

  vm.removeDoc = function(e, index){
    e.preventDefault();
    vm.request.docs.splice(index, 1);
  }

  vm.removePlace = function(e, index){
    e.preventDefault();
    vm.request.authorization.places.splice(index, 1);
  }

  vm.addPlace = function(newPlace){
    var isDuplicate = vm.request.authorization.places.some(function(place){
      return newPlace.id == place.id;
    });
    if (!isDuplicate){
      vm.request.authorization.places.push(newPlace);
      vm.newPlace = undefined;
    }
  }

  // $scope.dateOptions = {
  //   maxDate: new Date(2020, 5, 22),
  //   startingDay: 1
  // };


});


})();